try:
    import uasyncio as asyncio
except ImportError:
    import asyncio


AWG_TABLE = {
    18: {"bare": 1.024, "magnet": 1.06, "stranded": 2.0},
    19: {"bare": 0.912, "magnet": 0.95, "stranded": 1.8},
    20: {"bare": 0.812, "magnet": 0.85, "stranded": 1.6},
    21: {"bare": 0.723, "magnet": 0.76, "stranded": 1.5},
    22: {"bare": 0.644, "magnet": 0.68, "stranded": 1.4},
    23: {"bare": 0.573, "magnet": 0.61, "stranded": 1.3},
    24: {"bare": 0.511, "magnet": 0.55, "stranded": 1.2},
    25: {"bare": 0.455, "magnet": 0.49, "stranded": 1.1},
    26: {"bare": 0.405, "magnet": 0.44, "stranded": 1.0},
    27: {"bare": 0.361, "magnet": 0.40, "stranded": 0.9},
    28: {"bare": 0.321, "magnet": 0.36, "stranded": 0.8},
    29: {"bare": 0.286, "magnet": 0.32, "stranded": 0.75},
    30: {"bare": 0.255, "magnet": 0.29, "stranded": 0.70},
    31: {"bare": 0.227, "magnet": 0.26, "stranded": 0.65},
    32: {"bare": 0.202, "magnet": 0.23, "stranded": 0.60},
    33: {"bare": 0.180, "magnet": 0.21, "stranded": 0.55},
    34: {"bare": 0.160, "magnet": 0.19, "stranded": 0.50},
    35: {"bare": 0.143, "magnet": 0.17, "stranded": 0.45},
    36: {"bare": 0.127, "magnet": 0.15, "stranded": 0.40},
}


def get_awg_diameter(awg_size, wire_type="magnet"):
    try:
        gauge = int(awg_size)
    except (TypeError, ValueError):
        raise ValueError("awg_size must be an integer AWG value")

    if wire_type not in ("bare", "magnet", "stranded"):
        raise ValueError("wire_type must be one of: bare, magnet, stranded")

    if gauge not in AWG_TABLE:
        min_awg = min(AWG_TABLE)
        max_awg = max(AWG_TABLE)
        raise ValueError(f"AWG {gauge} is not supported. Supported range: {min_awg}-{max_awg}")

    return AWG_TABLE[gauge][wire_type]

def compute_layer_steps(spool_width_mm, wire_diameter_mm):
    STEPS_PER_REV = 200
    LEAD_MM = 1.25  # M3x1.25

    steps_per_turn = STEPS_PER_REV * (wire_diameter_mm / LEAD_MM)
    turns_per_layer = int(spool_width_mm // wire_diameter_mm)

    odd_turns = turns_per_layer + 1
    even_turns = turns_per_layer

    odd_steps = round(odd_turns * steps_per_turn)
    even_steps = round(even_turns * steps_per_turn)

    return odd_steps, even_steps, steps_per_turn

def winding_plan(total_turns, spool_width_mm, wire_diameter_mm):
    odd_steps, even_steps, steps_per_turn = compute_layer_steps(
        spool_width_mm, wire_diameter_mm
    )

    turns_per_pair = (odd_steps + even_steps) / steps_per_turn
    layers = []

    remaining = total_turns
    layer_num = 1

    while remaining > 0:
        if layer_num % 2 == 1:  # odd layer
            turns = int(spool_width_mm // wire_diameter_mm) + 1
            steps = odd_steps
        else:
            turns = int(spool_width_mm // wire_diameter_mm)
            steps = even_steps

        layers.append((layer_num, turns, steps))
        remaining -= turns
        layer_num += 1

    return layers


def winding_plan_summary(total_turns, layers):
    actual_turns = sum(turns for _, turns, _ in layers)
    return {
        "requested_turns": total_turns,
        "actual_turns": actual_turns,
        "overrun_turns": actual_turns - total_turns,
        "layer_count": len(layers),
    }


def winding_plan_from_awg(total_turns, spool_width_mm, awg_size, wire_type="magnet"):
    wire_diameter_mm = get_awg_diameter(awg_size, wire_type)
    return winding_plan(total_turns, spool_width_mm, wire_diameter_mm)


async def _example_heartbeat(stop_flag):
    while not stop_flag[0]:
        await asyncio.sleep_ms(250)


async def _async_example():
    total_turns = 300
    spool_width_mm = 20.0
    awg_size = 20
    wire_type = "magnet"
    preview_count = 14

    stop_flag = [False]
    heartbeat_task = asyncio.create_task(_example_heartbeat(stop_flag))

    try:
        layers = winding_plan_from_awg(total_turns, spool_width_mm, awg_size, wire_type)
        summary = winding_plan_summary(total_turns, layers)

        print("Async winding plan example")
        print(f"AWG: {awg_size} ({wire_type})")
        print(f"Total turns: {total_turns}")
        print(f"Spool width: {spool_width_mm} mm")
        print(f"Layers generated: {summary['layer_count']}")
        print(f"Actual planned turns: {summary['actual_turns']}")
        print(f"Overrun turns: {summary['overrun_turns']}")

        
        for layer_num, turns, steps in layers[:preview_count]:
            print(f"Layer {layer_num}: turns={turns}, steps={steps}")
            await asyncio.sleep_ms(0)

        if len(layers) > preview_count:
            print(f"... ({len(layers) - preview_count} more layers)")
    finally:
        stop_flag[0] = True
        await heartbeat_task


if __name__ == "__main__":
    asyncio.run(_async_example())