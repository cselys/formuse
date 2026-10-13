"""
State tracker module for Paper Validation subsystem.
Tracks subsequent scanner states for each paper signal and builds transition history.
"""

import os
import json
import logging
import pandas as pd
from typing import Dict, List, Any, Optional

logger = logging.getLogger("stock_scanner.paper.statetracker")


class StateTracker:
    """Tracks state transitions of paper signals across daily scan snapshots."""

    def __init__(self, signals_dir: str = "data/paper_validation/signals", outcomes_dir: str = "data/paper_validation/outcomes"):
        self.signals_dir = signals_dir
        self.outcomes_dir = outcomes_dir

    def update_state_transitions(self) -> Dict[str, Any]:
        """
        Scan all available daily scan snapshots (`YYYY-MM-DD.json`) and update
        state transition paths for active paper signals in outcome files.
        """
        if not os.path.exists(self.signals_dir) or not os.path.exists(self.outcomes_dir):
            return {"updated_signals": 0}

        # Gather all snapshot files (named YYYY-MM-DD.json or YYYY-MM-DD_v*.json)
        all_files = os.listdir(self.signals_dir)
        snapshot_files = [f for f in all_files if f.endswith(".json") and not f.startswith("signals_")]
        snapshot_files.sort()

        # Build symbol-date to state mapping from snapshots
        # date_symbol_states[date_str][symbol] = state
        date_symbol_states = {}
        for sf in snapshot_files:
            # Extract date part e.g. 2026-09-01
            parts = sf.replace(".json", "").split("_")
            date_str = parts[0]
            if len(date_str) != 10 or date_str[4] != '-' or date_str[7] != '-':
                continue

            path = os.path.join(self.signals_dir, sf)
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                syms = data.get("symbols", [])
                if date_str not in date_symbol_states:
                    date_symbol_states[date_str] = {}
                for s in syms:
                    sym = s.get("symbol")
                    st = s.get("state")
                    if sym and st:
                        date_symbol_states[date_str][sym] = st
            except Exception as e:
                logger.warning(f"Error reading snapshot {sf}: {e}")

        # Now update outcome files
        outcome_files = [f for f in os.listdir(self.outcomes_dir) if f.startswith("outcome_") and f.endswith(".json")]
        updated_count = 0

        for out_file in outcome_files:
            outcomes_path = os.path.join(self.outcomes_dir, out_file)
            try:
                with open(outcomes_path, 'r', encoding='utf-8') as f:
                    outcomes = json.load(f)

                changed = False
                for outcome in outcomes:
                    signal_date = outcome['signal_date']
                    symbol = outcome['symbol']

                    # Find all snapshot dates >= signal_date
                    transition_path = []
                    for d_str in sorted(date_symbol_states.keys()):
                        if d_str >= signal_date:
                            if symbol in date_symbol_states[d_str]:
                                st = date_symbol_states[d_str][symbol]
                                transition_path.append({"date": d_str, "state": st})

                    if transition_path:
                        outcome['state_transitions'] = transition_path
                        changed = True
                        updated_count += 1

                if changed:
                    with open(outcomes_path, 'w', encoding='utf-8') as f:
                        json.dump(outcomes, f, indent=2)

            except Exception as e:
                logger.warning(f"Error updating state transitions for {out_file}: {e}")

        logger.info(f"Updated state transitions for {updated_count} signal outcome records.")
        return {"updated_signals": updated_count}
