import json
from typing import Any

from prometheus_client import Counter, Histogram, exposition

from knot_resolver_manager.datamodel.config_schema import KresConfig
from knot_resolver_manager.kres_id import KresID
from knot_resolver_manager.kres_manager import KresManager

KRESD_RESPONSE_LATENCY = Histogram(
    "kresd_response_latency",
    "Time it takes to respond to queries in seconds",
    buckets=[0.001, 0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 1.5, float("inf")],
    labelnames=["instance_id"],
)
KRESD_REQUEST_TOTAL = Counter(
    "kresd_request_total",
    "total number of DNS requests (including internal client requests)",
    labelnames=["instance_id"],
)
KRESD_REQUEST_INTERNAL = Counter(
    "kresd_request_internal",
    "number of internal requests generated by Knot Resolver (e.g. DNSSEC trust anchor updates)",
    labelnames=["instance_id"],
)
KRESD_REQUEST_UDP = Counter(
    "kresd_request_udp", "number of external requests received over plain UDP (RFC 1035)", labelnames=["instance_id"]
)
KRESD_REQUEST_TCP = Counter(
    "kresd_request_tcp", "number of external requests received over plain TCP (RFC 1035)", labelnames=["instance_id"]
)
KRESD_REQUEST_DOT = Counter(
    "kresd_request_dot", "number of external requests received over DNS-over-TLS (RFC 7858)", labelnames=["instance_id"]
)
KRESD_REQUEST_DOH = Counter(
    "kresd_request_doh",
    "number of external requests received over DNS-over-HTTP (RFC 8484)",
    labelnames=["instance_id"],
)
KRESD_REQUEST_XDP = Counter(
    "kresd_request_xdp",
    "number of external requests received over plain UDP via an AF_XDP socket",
    labelnames=["instance_id"],
)
KRESD_ANSWER_TOTAL = Counter("kresd_answer_total", "total number of answered queries", labelnames=["instance_id"])
KRESD_ANSWER_CACHED = Counter(
    "kresd_answer_cached", "number of queries answered from cache", labelnames=["instance_id"]
)

KRESD_ANSWER_RCODE_NOERROR = Counter(
    "kresd_answer_rcode_noerror", "number of NOERROR answers", labelnames=["instance_id"]
)
KRESD_ANSWER_RCODE_NODATA = Counter(
    "kresd_answer_rcode_nodata", "number of NOERROR answers without any data", labelnames=["instance_id"]
)
KRESD_ANSWER_RCODE_NXDOMAIN = Counter(
    "kresd_answer_rcode_nxdomain", "number of NXDOMAIN answers", labelnames=["instance_id"]
)
KRESD_ANSWER_RCODE_SERVFAIL = Counter(
    "kresd_answer_rcode_servfail", "number of SERVFAIL answers", labelnames=["instance_id"]
)

KRESD_ANSWER_FLAG_AA = Counter("kresd_answer_flag_aa", "number of authoritative answers", labelnames=["instance_id"])
KRESD_ANSWER_FLAG_TC = Counter("kresd_answer_flag_tc", "number of truncated answers", labelnames=["instance_id"])
KRESD_ANSWER_FLAG_RA = Counter(
    "kresd_answer_flag_ra", "number of answers with recursion available flag", labelnames=["instance_id"]
)
KRESD_ANSWER_FLAG_RD = Counter(
    "kresd_answer_flags_rd", "number of recursion desired (in answer!)", labelnames=["instance_id"]
)
KRESD_ANSWER_FLAG_AD = Counter(
    "kresd_answer_flag_ad", "number of authentic data (DNSSEC) answers", labelnames=["instance_id"]
)
KRESD_ANSWER_FLAG_CD = Counter(
    "kresd_answer_flag_cd", "number of checking disabled (DNSSEC) answers", labelnames=["instance_id"]
)
KRESD_ANSWER_FLAG_DO = Counter("kresd_answer_flag_do", "number of DNSSEC answer OK", labelnames=["instance_id"])
KRESD_ANSWER_FLAG_EDNS0 = Counter(
    "kresd_answer_flag_edns0", "number of answers with EDNS0 present", labelnames=["instance_id"]
)

KRESD_QUERY_EDNS = Counter("kresd_query_edns", "number of queries with EDNS present", labelnames=["instance_id"])
KRESD_QUERY_DNSSEC = Counter("kresd_query_dnssec", "number of queries with DNSSEC DO=1", labelnames=["instance_id"])


def _generate_instance_metrics(instance_id: KresID, metrics: Any) -> None:
    # Uses private fields in order to translate kresd statistics into prometheus's library internal objects.
    # pylint: disable=protected-access

    sid = str(instance_id)

    # response latency histogram
    for i, duration in enumerate(("1ms", "10ms", "50ms", "100ms", "250ms", "500ms", "1000ms", "1500ms", "slow")):
        KRESD_RESPONSE_LATENCY.labels(str(sid))._buckets[i].set(metrics[f"answer.{duration}"])
    # TODO add sum after fixing https://gitlab.nic.cz/knot/knot-resolver/-/issues/721
    # KRESD_RESPONSE_LATENCY.labels(str(id))._sum.set(sum)

    KRESD_REQUEST_TOTAL.labels(str(sid))._value.set(metrics["request.total"])
    KRESD_REQUEST_INTERNAL.labels(str(sid))._value.set(metrics["request.internal"])
    KRESD_REQUEST_UDP.labels(str(sid))._value.set(metrics["request.udp"])
    KRESD_REQUEST_TCP.labels(str(sid))._value.set(metrics["request.tcp"])
    KRESD_REQUEST_DOT.labels(str(sid))._value.set(metrics["request.dot"])
    KRESD_REQUEST_DOH.labels(str(sid))._value.set(metrics["request.doh"])
    KRESD_REQUEST_XDP.labels(str(sid))._value.set(metrics["request.xdp"])

    KRESD_ANSWER_TOTAL.labels(str(sid))._value.set(metrics["answer.total"])
    KRESD_ANSWER_CACHED.labels(str(sid))._value.set(metrics["answer.cached"])

    KRESD_ANSWER_RCODE_NOERROR.labels(str(sid))._value.set(metrics["answer.noerror"])
    KRESD_ANSWER_RCODE_NODATA.labels(str(sid))._value.set(metrics["answer.nodata"])
    KRESD_ANSWER_RCODE_NXDOMAIN.labels(str(sid))._value.set(metrics["answer.nxdomain"])
    KRESD_ANSWER_RCODE_SERVFAIL.labels(str(sid))._value.set(metrics["answer.servfail"])

    KRESD_ANSWER_FLAG_AA.labels(str(sid))._value.set(metrics["answer.aa"])
    KRESD_ANSWER_FLAG_TC.labels(str(sid))._value.set(metrics["answer.tc"])
    KRESD_ANSWER_FLAG_RA.labels(str(sid))._value.set(metrics["answer.ra"])
    KRESD_ANSWER_FLAG_RD.labels(str(sid))._value.set(metrics["answer.rd"])
    KRESD_ANSWER_FLAG_AD.labels(str(sid))._value.set(metrics["answer.ad"])
    KRESD_ANSWER_FLAG_CD.labels(str(sid))._value.set(metrics["answer.cd"])
    KRESD_ANSWER_FLAG_DO.labels(str(sid))._value.set(metrics["answer.do"])
    KRESD_ANSWER_FLAG_EDNS0.labels(str(sid))._value.set(metrics["answer.edns0"])

    KRESD_QUERY_EDNS.labels(str(sid))._value.set(metrics["query.edns"])
    KRESD_QUERY_DNSSEC.labels(str(sid))._value.set(metrics["query.dnssec"])


async def collect(_config: KresConfig, manager: KresManager) -> bytes:
    """
    Collects metrics from everything, returns data string in Prometheus format.
    """

    ON_DEMAND_STATS_QUERY = "collect_lazy_statistics()"
    STATS_QUERY = "collect_statistics()"

    cmd = ON_DEMAND_STATS_QUERY
    stats_raw = await manager.command_all(cmd)

    for id, raw in stats_raw.items():
        metrics = json.loads(raw[1:-1])
        _generate_instance_metrics(id, metrics)

    return exposition.generate_latest()
