"""
Module to run the workflow.
"""

import asyncio
import uuid
import os
import json
import re

from flask import Flask, jsonify, request, render_template, send_from_directory
from temporalio.client import Client
from temporalio.common import QueryRejectCondition
from temporalio.service import RPCError

from shared import TASK_QUEUE_NAME, BookVacationInput
from workflows import BookingWorkflow


def create_app(temporal_client: Client):
    app = Flask(__name__)

    # Create static folder if it doesn't exist
    os.makedirs(os.path.join(os.path.dirname(__file__), 'static'), exist_ok=True)

    def generate_unique_username(name):
        return f'{name.replace(" ", "-").lower()}-{str(uuid.uuid4().int)[:6]}'

    @app.route('/')
    def index():
        """Serve the booking form page."""
        return render_template('index.html')

    @app.route('/static/<path:path>')
    def serve_static(path):
        """Serve static files."""
        return send_from_directory('static', path)

    @app.route("/book", methods=["POST"])
    async def book_vacation():
        """
        Endpoint to book a vacation.

        Returns:
            Response: JSON response with booking details or error message.
        """
        user_id = generate_unique_username(request.json.get("name"))
        attempts = request.json.get("attempts")
        car = request.json.get("car")
        hotel = request.json.get("hotel")
        flight = request.json.get("flight")

        input_data = BookVacationInput(
            attempts=int(attempts),
            book_user_id=user_id,
            book_car_id=car,
            book_hotel_id=hotel,
            book_flight_id=flight,
        )

        result = await temporal_client.execute_workflow(
            BookingWorkflow.run,
            input_data,
            id=user_id,
            task_queue=TASK_QUEUE_NAME,
        )

        # Determine the booking status based on the result
        status = "completed"

        # Check if this is a manual booking that needs approval
        needs_approval = False

        # Case 1: Check if result is a dictionary with a message containing manual_approval_needed
        if isinstance(result, dict):
            if "message" in result and isinstance(result["message"], dict):
                if "booked_hotel" in result["message"] and "manual_approval_needed" in str(result["message"]["booked_hotel"]):
                    status = "waiting_for_approval"
                    needs_approval = True
            # Case 2: Direct booked_hotel property
            elif "booked_hotel" in result and "manual_approval_needed" in str(result["booked_hotel"]):
                status = "waiting_for_approval"
                needs_approval = True

        # Case 3: Check if hotel ID starts with "manual"
        if hotel.startswith("manual"):
            status = "waiting_for_approval"
            needs_approval = True

        # Case 4: Check if result is a string containing manual_approval_needed
        if isinstance(result, str) and "manual_approval_needed" in result:
            status = "waiting_for_approval"
            needs_approval = True

        # Case 5: Check if result is "Voyage cancelled"
        if result == "Voyage cancelled":
            status = "cancelled"

        # Prepare the response
        response = {
            "user_id": user_id,
            "result": result,
            "status": status,
            "workflow_id": user_id  # Use the user_id as the workflow_id since that's what we use when creating the workflow
        }

        if needs_approval:
            response["needs_approval"] = True
            response["hotel_id"] = hotel

        if status == "cancelled":
            response["cancelled"] = True

        return jsonify(response)

    @app.route("/debug-workflows", methods=["GET"])
    async def debug_workflows():
        """
        Simple debug endpoint to list all running workflows.
        """
        workflows = []

        # Get all running workflows
        workflow_iterator = temporal_client.list_workflows(
            query="ExecutionStatus='Running'"
        )

        async for workflow in workflow_iterator:
            try:
                handle = temporal_client.get_workflow_handle(workflow.id)

                # Get basic workflow info
                workflow_info = {
                    "id": workflow.id,
                    "run_id": workflow.run_id if hasattr(workflow, "run_id") else "unknown",
                    "status": "Running"
                }

                # Try to get workflow description
                try:
                    desc = await handle.describe()
                    if hasattr(desc, 'workflow_execution_info'):
                        info = desc.workflow_execution_info
                        if hasattr(info, 'type') and hasattr(info.type, 'name'):
                            workflow_info["type"] = info.type.name
                        if hasattr(info, 'status'):
                            workflow_info["status"] = str(info.status)
                        if hasattr(info, 'start_time'):
                            workflow_info["start_time"] = str(info.start_time)
                except Exception as e:
                    workflow_info["describe_error"] = str(e)

                # Try to get workflow history to check for activities
                try:
                    history = await handle.fetch_history()
                    pending_activities = []

                    for event in history.events:
                        try:
                            # Check for activity started events that haven't completed
                            if hasattr(event, 'event_type') and hasattr(event.event_type, 'name') and event.event_type.name == 'EVENT_TYPE_ACTIVITY_TASK_SCHEDULED':
                                if hasattr(event, 'activity_task_scheduled_event_attributes'):
                                    attrs = event.activity_task_scheduled_event_attributes
                                    activity_id = attrs.activity_id if hasattr(attrs, 'activity_id') else "unknown"

                                    # Check if activity_type is an object with a name attribute
                                    activity_type = "unknown"
                                    if hasattr(attrs, 'activity_type'):
                                        if hasattr(attrs.activity_type, 'name'):
                                            activity_type = attrs.activity_type.name
                                        else:
                                            activity_type = str(attrs.activity_type)

                                    # Check if this activity has a completion event
                                    is_completed = False
                                    for completion_event in history.events:
                                        try:
                                            if (hasattr(completion_event, 'event_type') and
                                                hasattr(completion_event.event_type, 'name') and
                                                completion_event.event_type.name in ['EVENT_TYPE_ACTIVITY_TASK_COMPLETED',
                                                                                  'EVENT_TYPE_ACTIVITY_TASK_FAILED',
                                                                                  'EVENT_TYPE_ACTIVITY_TASK_CANCELED']):

                                                # Check if this completion event is for our activity
                                                if (hasattr(completion_event, 'activity_task_completed_event_attributes') and
                                                    hasattr(completion_event.activity_task_completed_event_attributes, 'scheduled_event_id') and
                                                    completion_event.activity_task_completed_event_attributes.scheduled_event_id == event.event_id):
                                                    is_completed = True
                                                    break
                                        except Exception as e:
                                            print(f"Error checking completion event: {str(e)}")
                                            continue

                                    if not is_completed:
                                        pending_activities.append({
                                            "id": activity_id,
                                            "type": activity_type
                                        })
                        except Exception as e:
                            print(f"Error processing event: {str(e)}")
                            continue

                    workflow_info["pending_activities"] = pending_activities

                    # Check if this workflow has a wait_for_human_approval activity
                    for activity in pending_activities:
                        if "wait_for_human_approval" in activity["type"]:
                            workflow_info["needs_approval"] = True

                            # Try to extract hotel ID from history
                            hotel_id = None
                            for event in history.events:
                                try:
                                    event_str = str(event)
                                    if "manual_" in event_str:
                                        match = re.search(r'manual_\w+', event_str)
                                        if match:
                                            hotel_id = match.group(0)
                                            break
                                except Exception as e:
                                    print(f"Error extracting hotel ID: {str(e)}")
                                    continue

                            if hotel_id:
                                workflow_info["hotel_id"] = hotel_id

                            break
                except Exception as e:
                    workflow_info["history_error"] = str(e)

                workflows.append(workflow_info)
            except Exception as e:
                workflows.append({
                    "id": workflow.id if hasattr(workflow, "id") else "unknown",
                    "error": str(e)
                })

        return jsonify({"workflows": workflows})

    @app.route("/pending-approvals", methods=["GET"])
    async def get_pending_approvals():
        """
        Get a list of pending hotel booking approvals.

        Returns:
            Response: JSON response with pending approvals.
        """
        print("Fetching pending approvals...")

        # Get all running workflows with a limit to avoid processing too many
        workflow_iterator = temporal_client.list_workflows(
            query="ExecutionStatus='Running'",
            page_size=50  # Limit the number of workflows to process
        )

        pending_approvals = []
        workflow_count = 0
        max_workflows = 100  # Set a maximum number of workflows to process

        # Process workflows in batches
        async for workflow in workflow_iterator:
            workflow_count += 1
            if workflow_count > max_workflows:
                break  # Stop processing after reaching the maximum

            print(f"Checking workflow: {workflow.id}")

            try:
                # Get the workflow handle
                handle = temporal_client.get_workflow_handle(workflow.id)

                # First check if this workflow has a wait_for_human_approval activity
                # by examining the pending activities
                try:
                    desc = await handle.describe()
                    history = await handle.fetch_history()

                    # Look for wait_for_human_approval activity in the history
                    needs_approval = False
                    hotel_id = None

                    # Method 1: Check for pending activities
                    for event in history.events:
                        try:
                            event_str = str(event)

                            # Look for wait_for_human_approval activity
                            if "wait_for_human_approval" in event_str:
                                needs_approval = True
                                print(f"Found wait_for_human_approval in workflow {workflow.id}")
                                break

                            # Look for manual booking indicators
                            if "manual_approval_needed" in event_str or "manual_" in event_str or "waiting_for_approval" in event_str:
                                needs_approval = True
                                print(f"Found manual booking indicator in workflow {workflow.id}")

                                # Try to extract hotel ID
                                match = re.search(r'manual_\w+', event_str)
                                if match:
                                    hotel_id = match.group(0)
                                    print(f"Found hotel ID in history: {hotel_id}")
                                break
                        except Exception as e:
                            print(f"Error examining event: {str(e)}")
                            continue

                    # Method 2: Check for specific activity types
                    if not needs_approval:
                        for event in history.events:
                            try:
                                if (hasattr(event, 'event_type') and
                                    hasattr(event.event_type, 'name') and
                                    event.event_type.name == 'EVENT_TYPE_ACTIVITY_TASK_SCHEDULED'):

                                    if hasattr(event, 'activity_task_scheduled_event_attributes'):
                                        attrs = event.activity_task_scheduled_event_attributes

                                        if hasattr(attrs, 'activity_type') and hasattr(attrs.activity_type, 'name'):
                                            activity_name = attrs.activity_type.name
                                            if activity_name == 'wait_for_human_approval':
                                                needs_approval = True
                                                print(f"Found wait_for_human_approval activity in workflow {workflow.id}")
                                                break
                            except Exception as e:
                                print(f"Error checking activity type: {str(e)}")
                                continue

                    # If we found a workflow that needs approval, add it to pending approvals
                    if needs_approval:
                        # Extract booking details
                        booking_details = {
                            "workflow_id": workflow.id,
                            "status": "waiting_for_approval"
                        }

                        if hotel_id:
                            booking_details["hotel_id"] = hotel_id

                        # Try to extract more details from the workflow
                        try:
                            if hasattr(desc, 'type') and hasattr(desc.type, 'name'):
                                booking_details["workflow_type"] = desc.type.name

                            if hasattr(desc, 'start_time'):
                                booking_details["start_time"] = str(desc.start_time)
                        except Exception as e:
                            print(f"Error extracting workflow details: {str(e)}")

                        print(f"Adding workflow to pending approvals: {workflow.id}")
                        pending_approvals.append({
                            "workflow_id": workflow.id,
                            "details": booking_details,
                            "started_at": str(desc.start_time) if hasattr(desc, 'start_time') else None,
                        })

                except Exception as e:
                    print(f"Error processing workflow history: {str(e)}")
                    continue

            except Exception as e:
                # Skip workflows that have errors
                print(f"Error processing workflow {workflow.id}: {str(e)}")
                continue

        print(f"Found {workflow_count} running workflows and {len(pending_approvals)} pending approvals")
        print(f"Pending approvals: {pending_approvals}")
        return jsonify({"pending_approvals": pending_approvals})

    @app.route("/approve-booking", methods=["POST"])
    def approve_booking():
        """Approve or reject a booking."""
        try:
            # Get data from request
            data = request.json
            workflow_id = data.get('workflow_id')
            decision = data.get('decision')

            if not workflow_id or not decision:
                return jsonify({"error": "Missing workflow_id or decision"}), 400

            print(f"Approving booking for workflow {workflow_id} with decision {decision}")
            
            # Use the CLI approach that we know works
            import subprocess
            import json
            
            # Escape the decision for the CLI
            escaped_decision = json.dumps(decision)
            
            # Build the command
            cmd = f"temporal workflow signal --workflow-id {workflow_id} --name approvalSignal --input {escaped_decision}"
            print(f"Running CLI command: {cmd}")
            
            # Run the command
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            
            if result.returncode == 0:
                print(f"Signal sent successfully via CLI: {result.stdout}")
                return jsonify({"success": True, "message": f"Booking {decision}d successfully"})
            else:
                print(f"Error sending signal via CLI: {result.stderr}")
                return jsonify({"error": f"Failed to send signal: {result.stderr}"}), 500
                
        except Exception as e:
            print(f"Error in approve_booking: {str(e)}")
            return jsonify({"error": str(e)}), 500

    @app.route("/approval-form", methods=["GET"])
    def approval_form():
        """
        Serve a simple form for approving/rejecting bookings.
        """
        return render_template('approval.html')

    @app.route("/test", methods=["GET"])
    def test_endpoint():
        """
        Simple test endpoint to verify server functionality.
        """
        print("Test endpoint called")
        return jsonify({"status": "ok", "message": "Server is running correctly"})

    @app.route("/test-approve/<workflow_id>", methods=["GET"])
    def test_approve(workflow_id):
        """Test endpoint to directly approve a booking."""
        try:
            print(f"Test approving booking for workflow {workflow_id}")
            
            # Get the workflow handle directly
            handle = temporal_client.get_workflow_handle(workflow_id)
            
            # Send the signal with the decision as a string
            print(f"Sending signal with decision: approve")
            handle.signal("approvalSignal", "approve")
            print(f"Signal sent successfully to workflow {workflow_id}")
            
            return jsonify({"success": True, "message": f"Test approval sent successfully"})
        except Exception as e:
            print(f"Error in test_approve: {str(e)}")
            return jsonify({"error": str(e)}), 500

    @app.route("/cli-approve/<workflow_id>", methods=["GET"])
    def cli_approve(workflow_id):
        """Test endpoint to directly approve a booking using the CLI."""
        try:
            print(f"CLI approving booking for workflow {workflow_id}")
            
            # Use subprocess to run the temporal CLI command
            import subprocess
            
            # Build the command
            cmd = f"temporal workflow signal --workflow-id {workflow_id} --name approvalSignal --input '\"approve\"'"
            print(f"Running CLI command: {cmd}")
            
            # Run the command
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            
            if result.returncode == 0:
                print(f"Signal sent successfully via CLI: {result.stdout}")
                return jsonify({"success": True, "message": f"CLI approval sent successfully", "output": result.stdout})
            else:
                print(f"Error sending signal via CLI: {result.stderr}")
                return jsonify({"error": f"Failed to send signal: {result.stderr}"}), 500
                
        except Exception as e:
            print(f"Error in cli_approve: {str(e)}")
            return jsonify({"error": str(e)}), 500

    return app


async def main():
    temporal_client = await Client.connect("localhost:7233")
    app = create_app(temporal_client)
    app.run(host="0.0.0.0", port=5050, debug=True)


if __name__ == "__main__":
    asyncio.run(main())
