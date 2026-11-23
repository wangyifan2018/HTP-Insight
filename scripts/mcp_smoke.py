import asyncio

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from htp_insight.core import ROOT, Core, atomic_write, encode
from htp_insight.interfaces import OPERATIONS


async def call(client, operation, arguments):
    result = await client.call_tool(operation, arguments)
    if result.isError or result.structuredContent is None:
        raise AssertionError(f"{operation} failed: {result.content}")
    return result.structuredContent


async def connect(core, baseline, candidate):
    config = StdioServerParameters(
        command="make", args=["--no-print-directory", "mcp"], cwd=str(ROOT),
        env={"HTP_INSIGHT_DATA": str(core.root), "HTP_INSIGHT_WEB": core.web_url},
    )
    async with stdio_client(config) as (read, write):
        async with ClientSession(read, write) as client:
            init = await client.initialize()
            listed = sorted(tool.name for tool in (await client.list_tools()).tools)
            assert listed == sorted(OPERATIONS)
            profile = core.session(baseline)
            graph = await call(client, "inspect_graph", {"model_id": profile.model_id})
            hotspots = await call(client, "get_hotspots", {"profile_id": baseline})
            assert hotspots == core.get_hotspots(baseline)
            best = hotspots["hotspots"][0]["id"]
            explanation = await call(client, "explain_hotspot", {"profile_id": baseline, "hotspot_id": best})
            assert explanation == core.explain_hotspot(baseline, best)
            suggestions = await call(client, "suggest_experiments", {"profile_id": baseline})
            assert suggestions == core.suggest_experiments(baseline)
            return {
                "protocol": init.protocolVersion, "server": init.serverInfo.name, "tools": listed,
                "graph": {"id": graph["artifact"]["id"], "nodes": len(graph["nodes"]), "deep_link": graph["deep_link"]},
                "hotspots": hotspots, "explanation": explanation, "suggestions": suggestions,
                "comparison": await call(client, "compare_experiments", candidate),
            }


if __name__ == "__main__":
    import json
    core = Core()
    demo = json.loads((core.root / "demo.json").read_bytes())
    args = {key: demo[key] for key in ("baseline", "candidate", "hypothesis")}
    report = asyncio.run(connect(core, demo["baseline"], args))
    assert report["comparison"] == core.read(demo["id"], "experiment.json")
    assert report["comparison"]["latency"] == demo["latency"]
    output = core.root / "verification/mcp.json"
    atomic_write(output, encode(report))
    print(f"MCP stdio {report['protocol']}, {len(report['tools'])} tools, {report['comparison']['id']} → {output}")
