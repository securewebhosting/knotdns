#include "daemon/ratelimiting.h"
#include "daemon/mmapped.h"
#include "lib/kru.h"
#include "lib/utils.h"
#include "lib/resolve.h"

#define RRL_V4_PREFIXES  (uint8_t[])       {  18,  20, 24, 32 }
#define RRL_V4_RATE_MULT (kru_price_t[])   { 768, 256, 32,  1 }

#define RRL_V6_PREFIXES  (uint8_t[])       { 32, 48, 56, 64, 128 }
#define RRL_V6_RATE_MULT (kru_price_t[])   { 64,  4,  3,  2,   1 }

#define RRL_V4_PREFIXES_CNT (sizeof(RRL_V4_PREFIXES) / sizeof(*RRL_V4_PREFIXES))
#define RRL_V6_PREFIXES_CNT (sizeof(RRL_V6_PREFIXES) / sizeof(*RRL_V6_PREFIXES))
#define RRL_MAX_PREFIXES_CNT ((RRL_V4_PREFIXES_CNT > RRL_V6_PREFIXES_CNT) ? RRL_V4_PREFIXES_CNT : RRL_V6_PREFIXES_CNT)

struct ratelimiting {
	size_t capacity;
	uint32_t instant_limit;
	uint32_t rate_limit;
	uint16_t tc_limit;
	bool using_avx2;
	kru_price_t v4_prices[RRL_V4_PREFIXES_CNT];
	kru_price_t v6_prices[RRL_V6_PREFIXES_CNT];
	uint8_t kru[] ALIGNED(64);
};
struct ratelimiting *ratelimiting = NULL;
struct mmapped ratelimiting_mmapped = {0};

/// return whether we're using optimized variant right now
static bool using_avx2(void)
{
	bool result = (KRU.initialize == KRU_AVX2.initialize);
	kr_require(result || KRU.initialize == KRU_GENERIC.initialize);
	return result;
}

int ratelimiting_init(const char *mmap_file, size_t capacity, uint32_t instant_limit, uint32_t rate_limit, int tc_limit_perc)
{

	size_t capacity_log = 0;
	for (size_t c = capacity - 1; c > 0; c >>= 1) capacity_log++;

	size_t size = offsetof(struct ratelimiting, kru) + KRU.get_size(capacity_log);
	size_t header_size = offsetof(struct ratelimiting, v4_prices);

	struct ratelimiting header = {
		.capacity = capacity,
		.instant_limit = instant_limit,
		.rate_limit = rate_limit,
		.tc_limit = (tc_limit_perc == 100 ? -1 : ((uint32_t)tc_limit_perc << 16) / 100),
		.using_avx2 = using_avx2()
	};

	int ret = mmapped_init(&ratelimiting_mmapped, mmap_file, size, &header, header_size);
	if (ret == MMAPPED_WAS_FIRST) {
		kr_log_info(SYSTEM, "Initializing rate-limiting...\n");

		ratelimiting = ratelimiting_mmapped.mem;

		const kru_price_t base_price = KRU_LIMIT / instant_limit;
		const kru_price_t max_decay = rate_limit > 1000ll * instant_limit ? base_price :
			(uint64_t) base_price * rate_limit / 1000;

		bool succ = KRU.initialize((struct kru *)ratelimiting->kru, capacity_log, max_decay);
		kr_require(succ);

		for (size_t i = 0; i < RRL_V4_PREFIXES_CNT; i++) {
			ratelimiting->v4_prices[i] = base_price / RRL_V4_RATE_MULT[i];
		}

		for (size_t i = 0; i < RRL_V6_PREFIXES_CNT; i++) {
			ratelimiting->v6_prices[i] = base_price / RRL_V6_RATE_MULT[i];
		}

		ret = mmapped_init_continue(&ratelimiting_mmapped);
		if (ret != 0) goto fail;

		kr_log_info(SYSTEM, "Rate-limiting initialized (%s).\n", (ratelimiting->using_avx2 ? "AVX2" : "generic"));
		return 0;
	} else if (ret == 0) {
		ratelimiting = ratelimiting_mmapped.mem;
		kr_log_info(SYSTEM, "Using existing rate-limiting data (%s).\n", (ratelimiting->using_avx2 ? "AVX2" : "generic"));
		return 0;
	} // else fail

fail:

	kr_log_crit(SYSTEM, "Initialization of shared rate-limiting data failed.\n");

	return ret;
}

void ratelimiting_deinit(void)
{
	if (ratelimiting == NULL) return;

	mmapped_deinit(&ratelimiting_mmapped);
	ratelimiting = NULL;
}


bool ratelimiting_request_begin(struct kr_request *req)
{
	if (!req->qsource.addr)
		return false;  // don't consider internal requests
	uint8_t limited = 0;  // 0: not limited, 1: truncated, 2: no answer
	if (ratelimiting) {
		uint8_t key[16] ALIGNED(16) = {0, };
		uint8_t limited_prefix;
		uint16_t max_final_load = 0;
		if (req->qsource.addr->sa_family == AF_INET6) {
			struct sockaddr_in6 *ipv6 = (struct sockaddr_in6 *)req->qsource.addr;
			memcpy(key, &ipv6->sin6_addr, 16);

			limited_prefix = KRU.limited_multi_prefix_or((struct kru *)ratelimiting->kru, kr_now(),
					1, key, RRL_V6_PREFIXES, ratelimiting->v6_prices, RRL_V6_PREFIXES_CNT, &max_final_load);
		} else {
			struct sockaddr_in *ipv4 = (struct sockaddr_in *)req->qsource.addr;
			memcpy(key, &ipv4->sin_addr, 4);  // TODO append port?

			limited_prefix = KRU.limited_multi_prefix_or((struct kru *)ratelimiting->kru, kr_now(),
					0, key, RRL_V4_PREFIXES, ratelimiting->v4_prices, RRL_V4_PREFIXES_CNT, &max_final_load);
		}
		limited = (limited_prefix ? 2 : (max_final_load > ratelimiting->tc_limit ? 1 : 0));
	}
	if (!limited) return false;

	if (limited == 1) { // TC=1: return truncated reply to force source IP validation
		// We only do this on pure UDP.  (also TODO if cookies get implemented)
		const bool ip_validated = req->qsource.flags.tcp || req->qsource.flags.tls;
		if (ip_validated) return false;

		knot_pkt_t *answer = kr_request_ensure_answer(req);
		if (!answer) { // something bad; TODO: perhaps improve recovery from this
			kr_assert(false);
			return true;
		}
		// at this point the packet should be pretty clear

		// The TC=1 answer is not perfect, as the right RCODE might differ
		// in some cases, but @vcunat thinks that NOERROR isn't really risky here.
		knot_wire_set_tc(answer->wire);
		knot_wire_clear_ad(answer->wire);
		req->state = KR_STATE_DONE;
	} else {
		/*
		// Example limiting: REFUSED.
		knot_wire_set_rcode(answer->wire, KNOT_RCODE_REFUSED);
		kr_request_set_extended_error(req, KNOT_EDNS_EDE_OTHER, "YRAA: rate-limited");
		req->state = KR_STATE_DONE;
		*/

		// no answer
		req->options.NO_ANSWER = true;
		req->state = KR_STATE_FAIL;
	}

	return true;
}
