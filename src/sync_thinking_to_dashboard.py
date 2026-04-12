#!/usr/bin/env python3
"""
Thinking Stream Sync to Dashboard
=================================

Syncs the bot's thinking process to the Vercel dashboard.
This enables real-time visualization of:
- Data source accesses (KuCoin API, indicators, risk manager)
- Thought nodes showing analysis steps
- Signal calculations per pair
- Portfolio decisions

Usage:
    python3 sync_thinking_to_dashboard.py
    
The script polls /root/bot_thinking_stream.json every 2 seconds
and pushes updates to the dashboard via webhook or file sync.

Integration with Neural Thought Engine:
    https://hermes-agent-obsidian-view.vercel.app/thinking
"""

import json
import time
import os
import requests
from datetime import datetime
from pathlib import Path

# Configuration
THINKING_FILE = "/root/bot_thinking_stream.json"
WEBHOOK_URL = "http://localhost:3099/api/pushTradingThoughts"  # Local webhook
DASHBOARD_URL = "https://hermes-agent-obsidian-view.vercel.app"
VERCEL_SYNC_URL = f"{DASHBOARD_URL}/api/sync"  # Or custom endpoint

class ThinkingStreamSync:
    """Sync thinking stream to dashboard."""
    
    def __init__(self):
        self.last_mtime = 0
        self.last_content = None
        
    def read_thinking_stream(self) -> dict:
        """Read the current thinking stream from file."""
        try:
            if not os.path.exists(THINKING_FILE):
                return {}
            
            mtime = os.path.getmtime(THINKING_FILE)
            if mtime == self.last_mtime and self.last_content:
                return self.last_content
            
            with open(THINKING_FILE, 'r') as f:
                data = json.load(f)
            
            self.last_mtime = mtime
            self.last_content = data
            return data
            
        except Exception as e:
            print(f"[ERROR] Failed to read thinking stream: {e}")
            return {}
    
    def transform_to_graph_nodes(self, data: dict) -> dict:
        """Transform thinking data to dashboard graph format."""
        nodes = []
        edges = []
        
        timestamp = time.time()
        
        # Center node - Current stage
        stage = data.get("stage", "IDLE")
        stage_colors = {
            "IDLE": "#6c7086",
            "INITIALIZING": "#89b4fa",
            "GATHERING": "#f9e2af",
            "PROCESSING": "#fab387",
            "SYNTHESIZING": "#cba6f7",
            "ACTION": "#a6e3a1"
        }
        
        nodes.append({
            "id": "thought-center",
            "label": f"🧠 {stage}",
            "content": f"Stage: {stage}\nTimestamp: {datetime.now().strftime('%H:%M:%S')}",
            "x": 500,
            "y": 400,
            "color": stage_colors.get(stage, "#cdd6f4"),
            "size": 40,
            "shape": "circle"
        })
        
        # Data source nodes
        data_sources = data.get("data_sources", {})
        source_positions = [
            ("KuCoin API", 200, 200, "#89b4fa"),
            ("Indicators", 800, 200, "#fab387"),
            ("Risk Manager", 200, 600, "#f38ba8"),
            ("Portfolio", 800, 600, "#cba6f7"),
            ("Account", 500, 100, "#a6e3a1")
        ]
        
        for i, (name, default_x, default_y, color) in enumerate(source_positions):
            source_id = f"source_{name.lower().replace(' ', '_')}"
            info = data_sources.get(name.lower().replace(' ', '_'), {"active": True, "access_count": 0})
            
            nodes.append({
                "id": source_id,
                "label": name,
                "content": f"Accesses: {info.get('access_count', 0)}\nStatus: {'🟢 Active' if info.get('active') else '⚪ Idle'}",
                "x": default_x + (timestamp % 10),  # Slight jitter for animation
                "y": default_y + (timestamp % 5),
                "color": color if info.get("active") else "#313244",
                "size": 25 + min(15, info.get("access_count", 0) * 2),
                "shape": "hexagon"
            })
            
            # Edge from source to center
            edges.append({
                "id": f"edge_src_{i}",
                "source": source_id,
                "target": "thought-center",
                "color": color,
                "strength": min(1.0, info.get("access_count", 1) * 0.1),
                "style": "dashed" if not info.get("active") else "solid"
            })
        
        # Thought nodes
        thought_nodes = data.get("thought_nodes", [])
        for i, node in enumerate(thought_nodes[-10:]):  # Last 10 thoughts
            angle = (i / 10) * 2 * 3.14159
            radius = 250
            x = 500 + radius * (0.3 + (1 - node.get("confidence", 0.5)) * 0.7) * (1 if i % 2 else -1)
            y = 400 + radius * 0.5 * (i % 2)
            
            confidence = node.get("confidence", 0.5)
            node_colors = {
                "init": "#a6e3a1",
                "account": "#94e2d5",
                "signal_calc": "#fab387",
                "position_sizing": "#cba6f7",
                "trade": "#f38ba8" if confidence < 0.7 else "#a6e3a1",
                "critical_stop": "#f38ba8",
                "default": "#cdd6f4"
            }
            
            node_id = f"thought_{node.get('id', str(i))}"
            nodes.append({
                "id": node_id,
                "label": node.get("label", "..."),
                "content": f"Type: {node.get('type', 'thought')}\nConfidence: {confidence*100:.0f}%",
                "x": int(x),
                "y": int(y),
                "color": node_colors.get(node.get("type"), node_colors["default"]),
                "size": 15 + confidence * 20,
                "shape": "diamond" if node.get("type") == "trade" else "circle"
            })
            
            # Connect to center
            edges.append({
                "id": f"edge_thought_{i}",
                "source": node_id if confidence > 0.5 else "thought-center",
                "target": "thought-center" if confidence > 0.5 else node_id,
                "color": node_colors.get(node.get("type"), node_colors["default"]),
                "strength": confidence
            })
            
            # Connect to sources if mentioned
            for conn in node.get("connections", []):
                source_id = f"source_{conn}"
                if any(n["id"] == source_id for n in nodes):
                    edges.append({
                        "id": f"edge_conn_{i}_{conn}",
                        "source": source_id,
                        "target": node_id,
                        "color": "#89b4fa",
                        "strength": 0.5
                    })
        
        # Recent events as small activity nodes
        events = data.get("events", [])
        for i, event in enumerate(events[-5:]):
            angle = (i / 5) * 2 * 3.14159
            x = 500 + 350 * (0.5 + 0.5 * (1 if i % 2 else -1))
            y = 400 + (i - 2) * 100
            
            event_id = f"event_{int(time.time())}_{i}"
            event_type = event.get("type", "UNKNOWN")
            event_colors = {
                "DATA_ACCESS": "#89b4fa",
                "STAGE_CHANGE": "#f9e2af",
                "SIGNAL_CALC": "#fab387",
                "PORTFOLIO_DECISION": "#cba6f7",
                "THOUGHT_NODE": "#cdd6f4"
            }
            
            # Include data in content if available
            event_data = event.get("data", {})
            content = f"Type: {event_type}\n"
            if "pair" in event_data:
                content += f"Pair: {event_data['pair']}\n"
            if "signal" in event_data:
                content += f"Signal: {event_data['signal']}\n"
            if "composite" in event_data:
                content += f"Score: {event_data['composite']:.2f}"
            
            nodes.append({
                "id": event_id,
                "label": event_type.replace("_", " ").title(),
                "content": content,
                "x": int(x),
                "y": int(y),
                "color": event_colors.get(event_type, "#6c7086"),
                "size": 10,
                "shape": "square"
            })
            
            edges.append({
                "id": f"edge_event_{i}",
                "source": event_id,
                "target": "thought-center",
                "color": event_colors.get(event_type, "#6c7086"),
                "strength": 0.3
            })
        
        return {"nodes": nodes, "edges": edges, "timestamp": timestamp}
    
    def save_for_dashboard(self, graph_data: dict):
        """Save transformed data for dashboard consumption."""
        try:
            output_file = "/root/thinking_graph_state.json"
            with open(output_file, 'w') as f:
                json.dump(graph_data, f)
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Saved {len(graph_data['nodes'])} nodes to dashboard")
        except Exception as e:
            print(f"[ERROR] Failed to save dashboard data: {e}")
    
    def sync_to_vercel(self, graph_data: dict):
        """Sync to Vercel via API (requires auth)."""
        try:
            # This would need VERCEL_TOKEN
            # For now, just print what would be sent
            if os.getenv("VERCEL_TOKEN"):
                headers = {"Authorization": f"Bearer {os.getenv('VERCEL_TOKEN')}"}
                response = requests.post(
                    VERCEL_SYNC_URL,
                    json=graph_data,
                    headers=headers,
                    timeout=10
                )
                if response.status_code == 200:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] Synced to Vercel")
                else:
                    print(f"[WARN] Vercel sync failed: {response.status_code}")
        except Exception as e:
            pass  # Silent fail - dashboard can read from file
    
    def run(self):
        """Main sync loop."""
        print("")
        print("=" * 60)
        print("THINKING STREAM SYNC - Dashboard Integration")
        print("=" * 60)
        print(f"Watching: {THINKING_FILE}")
        print(f"Output: /root/thinking_graph_state.json")
        print(f"Dashboard: {DASHBOARD_URL}/thinking")
        print("")
        print("[INFO] The bot's thinking process will appear on the dashboard")
        print("[INFO] Start the bot with: python3 multi_pair_portfolio_trader_v5.py")
        print("")
        
        while True:
            try:
                thinking_data = self.read_thinking_stream()
                if thinking_data:
                    graph_data = self.transform_to_graph_nodes(thinking_data)
                    self.save_for_dashboard(graph_data)
                    self.sync_to_vercel(graph_data)
                
                time.sleep(2)  # Poll every 2 seconds
                
            except KeyboardInterrupt:
                print("\n[SHUTDOWN] Sync stopped")
                break
            except Exception as e:
                print(f"[ERROR] Sync error: {e}")
                time.sleep(5)


if __name__ == "__main__":
    sync = ThinkingStreamSync()
    sync.run()
