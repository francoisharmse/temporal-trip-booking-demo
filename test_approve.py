#!/usr/bin/env python3
"""
Simple script to test approving a workflow directly.
"""

import sys
from temporalio.client import Client

async def main():
    # Get the workflow ID from command line
    if len(sys.argv) < 2:
        print("Usage: python test_approve.py <workflow_id>")
        return
    
    workflow_id = sys.argv[1]
    print(f"Approving workflow: {workflow_id}")
    
    # Connect to Temporal server
    client = await Client.connect("localhost:7233")
    print("Connected to Temporal server")
    
    # Get the workflow handle
    handle = client.get_workflow_handle(workflow_id)
    print(f"Got workflow handle for {workflow_id}")
    
    # Send the signal
    await handle.signal("approvalSignal", "approve")
    print(f"Signal sent successfully to workflow {workflow_id}")

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
