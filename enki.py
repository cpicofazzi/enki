#!/usr/bin/env python3
"""
ENKI - Command Hub & Dual-Agent Orchestrator
Mesopotamian god of organization, crafts, wisdom, and civilization.
Coordinates Hermes (Knowledge/Context Agent) and Oh My Pi (OMP Terminal Coding Agent).
Supports OpenRouter and OpenCode Zen gateways.
"""

import sys
import json
import argparse
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.orchestrator import EnkiOrchestrator, PAYLOAD_FILE
from src.token_tracker import print_dashboard
from src.config import load_config

def resolve_preset(args, cfg):
    gateway = args.gateway
    model = args.model
    if getattr(args, "preset", None):
        preset_info = cfg.get("presets", {}).get(args.preset)
        if preset_info:
            gateway = gateway or preset_info.get("gateway")
            model = model or preset_info.get("hermes_model")
            print(f"[Preset: {preset_info.get('name')}] Gateway: {gateway} | Model: {model}")
    return gateway, model

def cmd_run(args):
    cfg = load_config()
    gw, md = resolve_preset(args, cfg)
    orchestrator = EnkiOrchestrator(gateway=gw, dry_run=getattr(args, "dry_run", False))
    orchestrator.run_pipeline(
        args.task,
        model_override=md,
        local_research=getattr(args, "local_research", True),
        find_research=getattr(args, "find_research", False)
    )

def cmd_context(args):
    cfg = load_config()
    gw, md = resolve_preset(args, cfg)
    orchestrator = EnkiOrchestrator(gateway=gw, dry_run=getattr(args, "dry_run", False))
    orchestrator.step_1_context_extraction(
        args.task,
        model_override=md,
        local_research=getattr(args, "local_research", True),
        find_research=getattr(args, "find_research", False)
    )

def cmd_handshake(args):
    orchestrator = EnkiOrchestrator(dry_run=getattr(args, "dry_run", False))
    payload_p = Path(args.payload) if args.payload else PAYLOAD_FILE
    orchestrator.step_2_execution_handshake(payload_p)

def cmd_verify(args):
    orchestrator = EnkiOrchestrator(dry_run=getattr(args, "dry_run", False))
    payload_p = Path(args.payload) if args.payload else PAYLOAD_FILE
    orchestrator.step_3_verification(payload_p)

def cmd_sync(args):
    orchestrator = EnkiOrchestrator(dry_run=getattr(args, "dry_run", False))
    payload_p = Path(args.payload) if args.payload else PAYLOAD_FILE
    orchestrator.step_4_sync(payload_p)

def cmd_monitor(args):
    print_dashboard()

def cmd_image(args):
    from src.openrouter import GatewayClient
    client = GatewayClient(gateway_name="openrouter")
    print(f"\n[Enki Image Generation] Generating image using model '{args.model or 'black-forest-labs/flux-1-schnell'}'...")
    print(f"  Prompt: {args.prompt}")
    res = client.generate_image(args.prompt, model=args.model)
    print(f"  Result: {res.get('content')}")
    print(f"  Tokens: {res.get('usage', {}).get('total_tokens', 0)} | Estimated Cost: ${res.get('usage', {}).get('cost_usd', 0.0):.4f}\n")

def cmd_gateway(args):
    cfg = load_config()
    cfg_file = ROOT_DIR / "config" / "enki.config.json"
    gateways = cfg.get("gateways", {})
    active = cfg.get("active_gateway", "openrouter")
    if getattr(args, "set", None):
        target = args.set.lower().strip()
        if target not in gateways:
            print(f"Error: Unknown gateway '{target}'. Available: {', '.join(gateways.keys())}")
            return
        try:
            with open(cfg_file, "r", encoding="utf-8") as f:
                c_data = json.load(f)
            c_data["active_gateway"] = target
            with open(cfg_file, "w", encoding="utf-8") as f:
                json.dump(c_data, f, indent=2)
            print(f"\n[+] Active gateway switched to: {gateways[target].get('name', target)} (`{target}`)\n")
        except Exception as e:
            print(f"Failed to update config: {e}")
        return

    if getattr(args, "test", False):
        print("=" * 64)
        print(" ENKI MODEL ROUTER CONNECTIVITY TEST")
        print("=" * 64)
        active_name = gateways.get(active, {}).get("name", active)
        base_url = gateways.get(active, {}).get("base_url", "https://openrouter.ai/api/v1")
        print(f" Active Gateway : {active_name} (`{active}`)")
        print(f" Router Base URL: {base_url}")

        # 1. Test Network & Public API Endpoint
        print("\n[1/3] Testing Router Reachability & Model Catalog...")
        from src.openrouter_catalog import OpenRouterCatalog
        import time
        try:
            t0 = time.time()
            cat = OpenRouterCatalog()
            live_models = cat.fetch_live_catalog()
            latency = round((time.time() - t0) * 1000, 1)
            if live_models:
                print(f"  [+] Connected! Reachable in {latency}ms ({len(live_models)} models cataloged).")
            else:
                print(f"  [!] Router reached, but catalog returned fallback list ({len(cat.get_catalog())} models).")
        except Exception as e:
            print(f"  [-] Connection failed: {e}")

        # 2. Test API Key Configuration
        print("\n[2/3] Checking Authentication & Credentials...")
        from src.openrouter import GatewayClient
        client = GatewayClient(gateway_name=active)
        has_key = bool(client.api_key)
        key_env = gateways.get(active, {}).get("api_key_env", "OPENROUTER_API_KEY")
        if has_key:
            masked = f"{client.api_key[:6]}...{client.api_key[-4:]}" if len(client.api_key) > 10 else "***"
            print(f"  [+] API key detected in environment ({key_env}: {masked}) - LIVE MODE READY")
        else:
            print(f"  [!] No active API key found for {key_env}.")
            print(f"      (Set {key_env} in .env to activate live API calls; currently operating in Simulation Mode)")

        # 3. Test Inference Probe
        print("\n[3/3] Sending Model Inference Probe...")
        probe_model = getattr(args, "model", None) or (
            client.default_hermes_model if has_key else "google/gemini-2.0-flash-001"
        )
        print(f"  * Probe Model: {probe_model}")
        try:
            t0 = time.time()
            res = client.complete(
                messages=[{"role": "user", "content": "Respond strictly with the single word: PONG"}],
                model=probe_model,
                agent_role="hermes",
                task_id="probe_connectivity"
            )
            dur = round((time.time() - t0) * 1000, 1)
            is_sim = res.get("usage", {}).get("simulated", False)
            mode_str = "[Simulation Mode]" if is_sim else "[Live Inference]"
            print(f"  [+] Response received in {dur}ms {mode_str}:")
            print(f"    Content : {res.get('content', '').strip()[:80]}")
            print(f"    Tokens  : {res.get('usage', {}).get('total_tokens', 0)} (Prompt: {res.get('usage', {}).get('prompt_tokens', 0)}, Comp: {res.get('usage', {}).get('completion_tokens', 0)})")
            print(f"    Cost    : ${res.get('usage', {}).get('cost_usd', 0.0):.6f}")
        except Exception as e:
            print(f"  [-] Inference probe failed: {e}")

        print("\n" + "=" * 64)
        return

    # Bare 'enki gateway' displays active gateway and available choices
    print("=" * 64)
    print(" ENKI AI MODEL GATEWAYS")
    print("=" * 64)
    active_name = gateways.get(active, {}).get("name", active)
    print(f" Active Gateway : {active_name} (`{active}`)")
    print("-" * 64)
    print(" Available Gateways:")
    for gw_id, gw_info in gateways.items():
        is_active = " [ACTIVE]" if gw_id == active else ""
        print(f"   * {gw_info.get('name', gw_id)} (`{gw_id}`){is_active}")
        print(f"     URL         : {gw_info.get('base_url')}")
        print(f"     Hermes Model: {gw_info.get('hermes_model')}")
        print(f"     OMP Model   : {gw_info.get('omp_model')}")
    print("=" * 64)
    print(" To switch gateway: enki gateway --set <gateway_id>\n")

def cmd_models(args):
    cfg = load_config()
    cfg_file = ROOT_DIR / "config" / "enki.config.json"
    active_gw = cfg.get("active_gateway", "openrouter")
    gw_info = cfg.get("gateways", {}).get(active_gw, {})
    projects = cfg.get("projects", {})

    modified = False
    if args.set_hermes or args.set_omp or (args.project and args.set_model):
        try:
            with open(cfg_file, "r", encoding="utf-8") as f:
                c_data = json.load(f)

            if args.set_hermes:
                c_data.setdefault("gateways", {}).setdefault(active_gw, {})["hermes_model"] = args.set_hermes
                print(f"[+] Updated Hermes model on {active_gw} to: {args.set_hermes}")
                modified = True

            if args.set_omp:
                c_data.setdefault("gateways", {}).setdefault(active_gw, {})["omp_model"] = args.set_omp
                print(f"[+] Updated OMP model on {active_gw} to: {args.set_omp}")
                modified = True

            if args.project and args.set_model:
                p_name = args.project
                c_data.setdefault("projects", {}).setdefault(p_name, {})["omp_model"] = args.set_model
                print(f"[+] Updated project '{p_name}' model to: {args.set_model}")
                modified = True

            if modified:
                with open(cfg_file, "w", encoding="utf-8") as f:
                    json.dump(c_data, f, indent=2)
                print("[+] Configuration successfully saved to enki.config.json\n")
        except Exception as e:
            print(f"Error updating model config: {e}")
        return

    print("=" * 68)
    print(" ENKI MODEL & TASK ARCHITECTURE")
    print("=" * 68)
    print(f" Active Gateway : {gw_info.get('name', active_gw)} (`{active_gw}`)")
    print(f" Hermes (Context) : {gw_info.get('hermes_model')}")
    print(f" OMP (Coding)     : {gw_info.get('omp_model')}")
    print("-" * 68)
    
    curated = gw_info.get("curated_leaders", {})
    if curated:
        print(" OPENROUTER DISCOVER LEADERS:")
        fl = curated.get("frontier_leaders", [])
        if fl:
            print("   [Frontier Leaders]")
            for item in fl:
                score_info = f"(AA Score: {item.get('intelligence_score')})" if item.get('intelligence_score') else f"({item.get('context', '')})"
                print(f"     * {item.get('name'):<20}: {item.get('model_id')} {score_info}")
                print(f"       Role: {item.get('role')}")
        vl = curated.get("value_leaders", [])
        if vl:
            print("\n   [Value Leaders (Capability Per Dollar)]")
            for item in vl:
                print(f"     * {item.get('name'):<20}: {item.get('model_id')}")
                print(f"       Rate: {item.get('pricing', 'N/A')} | {item.get('role')}")
        ch = curated.get("category_champions", {})
        if ch:
            print("\n   [Category Champions]")
            for cat, data in ch.items():
                cat_lbl = cat.replace("_", " ").title()
                print(f"     * {cat_lbl:<16}: {data.get('name')} ({data.get('model_id')}) - {data.get('metric')}")
        print("-" * 68)

    opencode_curated = gw_info.get("curated_leaderboard", {})
    if opencode_curated:
        print(" OPENCODE LEADERBOARD TOP MODELS (https://opencode.ai/data#leaderboard):")
        top_m = opencode_curated.get("top_models", [])
        for m in top_m:
            delta_str = f" ({m.get('delta')})" if m.get('delta') else ""
            cache_str = f" [Cache: {m.get('cache_ratio')}]" if m.get('cache_ratio') else ""
            print(f"   #{m.get('rank'):<2} {m.get('name'):<26}: {m.get('model_id')} ({m.get('provider')}) - {m.get('weekly_tokens')}/wk{delta_str}{cache_str}")
            if m.get("session_cost"):
                print(f"       Session Cost: {m.get('session_cost')}")
            if m.get("token_cost"):
                print(f"       Token Rates : {m.get('token_cost')}")
            if m.get("role"):
                print(f"       Role        : {m.get('role')}")
        eff = opencode_curated.get("efficiency_champions", {})
        if eff:
            print("\n   [OpenCode Efficiency Champions]")
            for key, data in eff.items():
                k_lbl = key.replace("_", " ").title()
                if isinstance(data, dict):
                    print(f"     * {k_lbl:<22}: {data.get('name')} ({data.get('model_id', '')}) - {data.get('metric')}")
                else:
                    print(f"     * {k_lbl:<22}: {data}")
        print("-" * 68)

    profiles = gw_info.get("task_profiles", {})
    if profiles:
        print(" TASK PROFILES & COMPLEXITY TIERS:")
        for category, tiers in profiles.items():
            cat_label = category.replace("_", " ").upper()
            print(f"\n   [{cat_label}]")
            if isinstance(tiers, dict):
                for tier, model_id in tiers.items():
                    print(f"     * {tier.capitalize():<22}: {model_id}")
            else:
                print(f"     * Note: {tiers}")
    print("\n" + "-" * 68)
    print(" PER-PROJECT OVERRIDES:")
    if not projects:
        print("   (No project-specific overrides set)")
    for p_name, p_cfg in projects.items():
        print(f"   [{p_name}]")
        print(f"     * Hermes: {p_cfg.get('hermes_model', gw_info.get('hermes_model'))}")
        print(f"     * OMP   : {p_cfg.get('omp_model', gw_info.get('omp_model'))}")
        print(f"     * Tests : {', '.join(p_cfg.get('test_commands', []))}")
    presets = cfg.get("presets", {})
    if presets:
        print("-" * 68)
        print(" CURATED PRESETS (--preset <name>):")
        for p_key, p_val in presets.items():
            print(f"   * {p_key:<20} : {p_val.get('name')} [{p_val.get('cost_profile')}]")
            print(f"                          Gateway: {p_val.get('gateway')} | Hermes: {p_val.get('hermes_model')} | OMP: {p_val.get('omp_model')}")
    print("-" * 68)
    print(" QUICK ASSIGNMENT COMMANDS:")
    print("   enki run --preset opencode_leader '<task>'")
    print("   enki run --preset opencode_ultra_value '<task>'")
    print("   enki run --preset opencode_pro '<task>'")
    print("   enki run --preset frontier '<task>'")
    print("   enki run --preset value_leader '<task>'")
    print("   enki run --preset sota '<task>'")
    print("   enki run --preset cost_optimal '<task>'")
    print("   enki run --preset free_tier '<task>'")
    print("   enki gateway --set opencode_zen")
    print("   enki gateway --set openrouter")
    print("   enki models --set-hermes <model_id>")
    print("   enki models --set-omp <model_id>")
    print("   enki models --project 'Project Name' --set-model <model_id>")
    print("   enki run --model <model_id> '<task>'")
    print("=" * 68)

def cmd_status(args):
    cfg = load_config()
    active_gw_id = cfg.get("active_gateway", "openrouter")
    gw_info = cfg.get("gateways", {}).get(active_gw_id, {})
    
    print("=" * 64)
    print(" ENKI STATUS & ENVIRONMENT OVERVIEW")
    print("=" * 64)
    print(f" Hub Name       : {cfg.get('hub_name')}")
    print(f" Active Gateway : {gw_info.get('name', active_gw_id)} (`{active_gw_id}`)")
    print(f" Gateway URL    : {gw_info.get('base_url')}")
    has_key = bool(gw_info.get("api_key"))
    key_env = gw_info.get("api_key_env", "KEY")
    print(f" API Key ({key_env}) : {'[Configured]' if has_key else '[Not set - Running in Simulation Mode]'}")
    print(f" Hermes Model   : {gw_info.get('hermes_model')}")
    print(f" OMP Model      : {gw_info.get('omp_model')}")
    print(f" Obsidian Vault : {cfg.get('obsidian', {}).get('vault_path')}")
    print("-" * 64)
    if PAYLOAD_FILE.is_file():
        try:
            with open(PAYLOAD_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            print(f" Active Payload : {PAYLOAD_FILE.name}")
            print(f" Task ID        : {data.get('task_id')}")
            print(f" Title          : {data.get('title')}")
            print(f" Status         : {data.get('status')}")
            print(f" Language       : {data.get('engineering_constraints', {}).get('language')}")
            print(f" Test Commands  : {', '.join(data.get('acceptance_criteria', {}).get('test_commands', []))}")
        except Exception as e:
            print(f" Error reading payload: {e}")
    else:
        print(" Active Payload : (No context_payload.json generated yet)")
    print("=" * 64)

def cmd_tui(args):
    """Launch interactive Terminal UI (Textual)."""
    from src.ui.tui.app import EnkiTUIApp
    app = EnkiTUIApp(
        dry_run=getattr(args, "dry_run", False),
        initial_workflow=getattr(args, "workflow", "four_step_pipeline")
    )
    app.run()

def cmd_serve(args):
    """Launch Web UI server (FastAPI + React) strictly on loopback (F34, F35)."""
    from src.web.server import run_server
    host = getattr(args, "host", "127.0.0.1")
    port = getattr(args, "port", 8765)
    reload = getattr(args, "reload", False)
    run_server(host=host, port=port, reload=reload)

def main():
    parser = argparse.ArgumentParser(
        description="Enki: Dual-Agent Command Hub for Antigravity, Hermes & Oh My Pi (OMP)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  enki run "Build normalization pipeline for Dinner Service Optimizer"
  enki run --gateway opencode_zen "Implement new feature"
  enki gateway
  enki gateway --set opencode_zen
  enki context "Build real-time Streamlit trend dashboard"
  enki monitor
  enki status
        """
    )
    subparsers = parser.add_subparsers(dest="subcommand", help="Command to run")

    # run
    p_run = subparsers.add_parser("run", help="Run full 4-step automated pipeline")
    p_run.add_argument("task", type=str, help="Feature request or task description")
    p_run.add_argument("--gateway", type=str, default="", help="Override gateway (openrouter | opencode_zen)")
    p_run.add_argument("--model", type=str, default="", help="Override model for this run")
    p_run.add_argument("--preset", choices=["frontier", "sota", "value_leader", "cost_optimal", "opencode_leader", "opencode_ultra_value", "opencode_pro", "free_tier"], default="", help="Select preset configuration")
    p_run.add_argument("--dry-run", action="store_true", help="Simulate pipeline without real model or OMP spend")
    p_run.add_argument("--no-local-research", dest="local_research", action="store_false", default=True, help="Disable local vault search during context step")
    p_run.add_argument("--find-research", dest="find_research", action="store_true", default=False, help="Search the internet, synthesize context, and create new Obsidian research note")
    p_run.set_defaults(func=cmd_run)

    # context
    p_ctx = subparsers.add_parser("context", help="Step 1: Hermes context & constraint extraction")
    p_ctx.add_argument("task", type=str, help="Feature request or task description")
    p_ctx.add_argument("--gateway", type=str, default="", help="Override gateway (openrouter | opencode_zen)")
    p_ctx.add_argument("--model", type=str, default="", help="Override model for context extraction")
    p_ctx.add_argument("--preset", choices=["frontier", "sota", "value_leader", "cost_optimal", "opencode_leader", "opencode_ultra_value", "opencode_pro", "free_tier"], default="", help="Select preset configuration")
    p_ctx.add_argument("--dry-run", action="store_true", help="Simulate context extraction without model spend")
    p_ctx.add_argument("--no-local-research", dest="local_research", action="store_false", default=True, help="Disable local vault search during context step")
    p_ctx.add_argument("--find-research", dest="find_research", action="store_true", default=False, help="Search the internet, synthesize context, and create new Obsidian research note")
    p_ctx.set_defaults(func=cmd_context)

    # handshake
    p_hs = subparsers.add_parser("handshake", help="Step 2: Feed context_payload.json to OMP")
    p_hs.add_argument("--payload", type=str, default="", help="Path to context_payload.json")
    p_hs.add_argument("--dry-run", action="store_true", help="Simulate handshake without running OMP")
    p_hs.set_defaults(func=cmd_handshake)

    # verify
    p_vf = subparsers.add_parser("verify", help="Step 3: Run OMP test suites and verification")
    p_vf.add_argument("--payload", type=str, default="", help="Path to context_payload.json")
    p_vf.add_argument("--dry-run", action="store_true", help="Simulate verification loop")
    p_vf.set_defaults(func=cmd_verify)

    # sync
    p_sc = subparsers.add_parser("sync", help="Step 4: Hermes logs completion to Obsidian")
    p_sc.add_argument("--payload", type=str, default="", help="Path to context_payload.json")
    p_sc.add_argument("--dry-run", action="store_true", help="Simulate completion logging")
    p_sc.set_defaults(func=cmd_sync)

    # gateway
    p_gw = subparsers.add_parser("gateway", help="View, switch, or test AI model gateways (OpenRouter / OpenCode Zen)")
    p_gw.add_argument("--set", type=str, default="", help="Switch active gateway (openrouter | opencode_zen)")
    p_gw.add_argument("--test", action="store_true", help="Test live connection to active gateway and model routers")
    p_gw.add_argument("--model", type=str, default="", help="Optional model override for connectivity test")
    p_gw.set_defaults(func=cmd_gateway)

    # models
    p_mod = subparsers.add_parser("models", help="Inspect and configure models for Hermes, OMP, and projects")
    p_mod.add_argument("--set-hermes", type=str, default="", help="Set Hermes model for active gateway")
    p_mod.add_argument("--set-omp", type=str, default="", help="Set OMP model for active gateway")
    p_mod.add_argument("--project", type=str, default="", help="Target project for per-project override")
    p_mod.add_argument("--set-model", type=str, default="", help="Set model for specified project")
    p_mod.set_defaults(func=cmd_models)

    # image
    p_img = subparsers.add_parser("image", help="Generate images using OpenRouter models (Flux-1 / DALL-E 3)")
    p_img.add_argument("prompt", type=str, help="Text description of the image to generate")
    p_img.add_argument("--model", type=str, default="black-forest-labs/flux-1-schnell", help="Image model override (flux-1-schnell, flux-1-dev, dall-e-3)")
    p_img.set_defaults(func=cmd_image)

    # monitor
    p_mon = subparsers.add_parser("monitor", help="Display token & cost monitor across gateways")
    p_mon.set_defaults(func=cmd_monitor)

    # status
    p_st = subparsers.add_parser("status", help="Show current Enki hub status and active gateway")
    p_st.set_defaults(func=cmd_status)

    # tui
    p_tui = subparsers.add_parser("tui", help="Launch interactive Terminal UI (Textual)")
    p_tui.add_argument("--dry-run", action="store_true", help="Launch TUI in simulation mode ($0.00 spend)")
    p_tui.add_argument("--workflow", type=str, default="four_step_pipeline", help="Pre-select initial workflow template")
    p_tui.set_defaults(func=cmd_tui)

    # serve
    p_srv = subparsers.add_parser("serve", help="Launch Web UI server (FastAPI + React)")
    p_srv.add_argument("--host", type=str, default="127.0.0.1", help="Host interface (must be loopback 127.0.0.1)")
    p_srv.add_argument("--port", type=int, default=8765, help="Port to listen on (default: 8765)")
    p_srv.add_argument("--reload", action="store_true", help="Enable hot reload for development")
    p_srv.set_defaults(func=cmd_serve)

    args = parser.parse_args()
    if not args.subcommand:
        parser.print_help()
        sys.exit(0)

    args.func(args)

if __name__ == "__main__":
    main()
