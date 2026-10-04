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
    orchestrator = EnkiOrchestrator(gateway=gw)
    orchestrator.run_pipeline(args.task, model_override=md)

def cmd_context(args):
    cfg = load_config()
    gw, md = resolve_preset(args, cfg)
    orchestrator = EnkiOrchestrator(gateway=gw)
    orchestrator.step_1_context_extraction(args.task, model_override=md)

def cmd_handshake(args):
    orchestrator = EnkiOrchestrator()
    payload_p = Path(args.payload) if args.payload else PAYLOAD_FILE
    orchestrator.step_2_execution_handshake(payload_p)

def cmd_verify(args):
    orchestrator = EnkiOrchestrator()
    payload_p = Path(args.payload) if args.payload else PAYLOAD_FILE
    orchestrator.step_3_verification(payload_p)

def cmd_sync(args):
    orchestrator = EnkiOrchestrator()
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

    if args.set:
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
    p_run.set_defaults(func=cmd_run)

    # context
    p_ctx = subparsers.add_parser("context", help="Step 1: Hermes context & constraint extraction")
    p_ctx.add_argument("task", type=str, help="Feature request or task description")
    p_ctx.add_argument("--gateway", type=str, default="", help="Override gateway (openrouter | opencode_zen)")
    p_ctx.add_argument("--model", type=str, default="", help="Override model for context extraction")
    p_ctx.add_argument("--preset", choices=["frontier", "sota", "value_leader", "cost_optimal", "opencode_leader", "opencode_ultra_value", "opencode_pro", "free_tier"], default="", help="Select preset configuration")
    p_ctx.set_defaults(func=cmd_context)

    # handshake
    p_hs = subparsers.add_parser("handshake", help="Step 2: Feed context_payload.json to OMP")
    p_hs.add_argument("--payload", type=str, default="", help="Path to context_payload.json")
    p_hs.set_defaults(func=cmd_handshake)

    # verify
    p_vf = subparsers.add_parser("verify", help="Step 3: Run OMP test suites and verification")
    p_vf.add_argument("--payload", type=str, default="", help="Path to context_payload.json")
    p_vf.set_defaults(func=cmd_verify)

    # sync
    p_sc = subparsers.add_parser("sync", help="Step 4: Hermes logs completion to Obsidian")
    p_sc.add_argument("--payload", type=str, default="", help="Path to context_payload.json")
    p_sc.set_defaults(func=cmd_sync)

    # gateway
    p_gw = subparsers.add_parser("gateway", help="View or switch AI model gateways (OpenRouter / OpenCode Zen)")
    p_gw.add_argument("--set", type=str, default="", help="Switch active gateway (openrouter | opencode_zen)")
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

    args = parser.parse_args()
    if not args.subcommand:
        parser.print_help()
        sys.exit(0)

    args.func(args)

if __name__ == "__main__":
    main()
