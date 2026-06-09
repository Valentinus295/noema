"""Entry point for live trading."""

import argparse
import asyncio
import os

from vmpm.agents.orchestrator import Orchestrator, OrchestratorState
from vmpm.broker.mt5 import MT5Broker
from vmpm.broker.fbs import FBSBroker


async def main():
    parser = argparse.ArgumentParser(description="VMPM Live Trading")
    parser.add_argument("--broker", choices=["fxpesa", "fbs"], default="fxpesa")
    parser.add_argument("--symbol", default="EURUSD")
    parser.add_argument("--interval", type=float, default=60.0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.broker == "fxpesa":
        broker = MT5Broker(
            host=os.getenv("MT5_HOST", "127.0.0.1"),
            port=int(os.getenv("MT5_PORT", "18812")),
            password=os.getenv("MT5_PASSWORD", ""),
        )
    else:
        broker = FBSBroker(
            host=os.getenv("MT5_HOST", "127.0.0.1"),
            port=int(os.getenv("MT5_PORT", "18813")),
            password=os.getenv("MT5_PASSWORD", ""),
        )

    state = OrchestratorState(symbol=args.symbol)
    orchestrator = Orchestrator(broker, state)

    await broker.connect()
    print(f"Connected to {args.broker} broker")

    try:
        await orchestrator.start(interval=args.interval)
        print("Trading started. Press Ctrl+C to stop.")
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        print("Stopping...")
    finally:
        await orchestrator.stop()
        await broker.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
