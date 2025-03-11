"""
Module for defining saga workflows.
"""

# @@@SNIPSTART saga-py-workflows-import
from datetime import timedelta
import asyncio

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from activities import (
        BookVacationInput,
        book_car,
        book_flight,
        book_hotel,
        complete_hotel_booking,
        undo_book_car,
        undo_book_flight,
        undo_book_hotel,
        wait_for_human_approval,
    )


@workflow.defn
class BookingWorkflow:
    """
    Workflow class for booking a vacation.
    """

    def __init__(self):
        self.approval_decision = None
        self._approval_received = False

    @workflow.signal
    def approvalSignal(self, details):
        """
        Signal handler for approval decisions.

        Args:
            details: Dictionary containing the decision (approve/reject)
        """
        workflow.logger.info(f"Received signal with details: {details}")

        # Set the approval decision directly
        self.approval_decision = str(details)
        self._approval_received = True
        workflow.logger.info(f"Set approval decision to: {self.approval_decision}")

    @workflow.run
    async def run(self, book_input: BookVacationInput):
        """
        Executes the booking workflow.

        Args:
            book_input (BookVacationInput): Input data for the workflow.

        Returns:
            str: Workflow result.
        """
        compensations = []
        results = {}
        try:
            compensations.append(undo_book_car)
            car_result = await workflow.execute_activity(
                book_car,
                book_input,
                start_to_close_timeout=timedelta(seconds=10),
            )
            results["booked_car"] = car_result

            # Book hotel
            compensations.append(undo_book_hotel)
            hotel_result = await workflow.execute_activity(
                book_hotel,
                book_input,
                start_to_close_timeout=timedelta(seconds=10),
                retry_policy=RetryPolicy(
                    non_retryable_error_types=["ValueError"],
                    maximum_attempts=book_input.attempts,
                ),
            )

            # Check if manual approval is needed for hotel booking
            needs_approval = False

            # First check if the hotel ID itself indicates manual approval is needed
            if book_input.book_hotel_id.startswith("manual_"):
                needs_approval = True
                workflow.logger.info(f"Manual approval needed based on hotel ID: {book_input.book_hotel_id}")
            # Then check the hotel result for manual approval indicators
            elif isinstance(hotel_result, str) and hotel_result.startswith("manual_approval_needed:"):
                needs_approval = True
                workflow.logger.info(f"Manual approval needed based on string result: {hotel_result}")
            elif isinstance(hotel_result, dict):
                # Only check for manual approval if the hotel ID starts with 'manual_'
                if book_input.book_hotel_id.startswith("manual_") and (
                    hotel_result.get("status") == "waiting_for_approval" or 
                    hotel_result.get("message") == "manual_approval_needed" or
                    hotel_result.get("manual_approval_needed") == True
                ):
                    needs_approval = True
                    workflow.logger.info(f"Manual approval needed based on dict result: {hotel_result}")

            if needs_approval:
                # Start the human approval activity
                workflow.logger.info(f"Manual approval needed for hotel: {book_input.book_hotel_id}")

                # Create a task for the wait_for_human_approval activity
                activity_handle = workflow.start_activity(
                    wait_for_human_approval,
                    book_input,
                    start_to_close_timeout=timedelta(minutes=30),
                    cancellation_type=workflow.ActivityCancellationType.WAIT_CANCELLATION_COMPLETED,
                )

                # Wait for the approval signal or a timeout
                approval_timeout = timedelta(minutes=10)
                workflow.logger.info(f"Waiting for approval signal with timeout of {approval_timeout}")

                # Define a helper function to wait for the signal
                async def wait_for_signal():
                    """Wait for the approval signal."""
                    workflow.logger.info("Starting to wait for approval signal")
                    
                    # Wait for the signal with polling
                    check_interval = 1  # seconds - check more frequently
                    max_wait_time = approval_timeout.total_seconds()
                    elapsed_time = 0
                    
                    while not self._approval_received and elapsed_time < max_wait_time:
                        # Log periodically but not too frequently
                        if elapsed_time % 5 == 0:  # Log every 5 seconds
                            workflow.logger.info(f"Waiting for approval signal... ({elapsed_time}/{max_wait_time} seconds)")
                        
                        # Short sleep to avoid busy waiting
                        await asyncio.sleep(check_interval)
                        elapsed_time += check_interval
                        
                        # Check if we received a signal
                        if self._approval_received:
                            workflow.logger.info(f"Signal received during wait! Decision: {self.approval_decision}")
                            return self.approval_decision
                    
                    if self._approval_received:
                        workflow.logger.info(f"Signal received! Decision: {self.approval_decision}")
                        return self.approval_decision
                    else:
                        workflow.logger.info("No signal received during polling period")
                        return None

                # Wait for either the signal or a timeout
                try:
                    # Reset approval state to ensure we're waiting for a fresh signal
                    self._approval_received = False
                    self.approval_decision = None
                    
                    # Convert timedelta to seconds for asyncio.wait_for
                    timeout_seconds = approval_timeout.total_seconds()
                    workflow.logger.info(f"Starting wait_for_signal with timeout {timeout_seconds} seconds")
                    approval_result = await asyncio.wait_for(wait_for_signal(), timeout_seconds)
                    workflow.logger.info(f"Signal received within timeout: {approval_result}")

                    # Cancel the activity since we got the signal
                    if not activity_handle.done():
                        workflow.logger.info("Cancelling wait_for_human_approval activity")
                        try:
                            # Force complete the activity instead of cancelling it
                            # This is more reliable than cancellation
                            workflow.logger.info("Force completing the activity")
                            activity_handle.complete({"status": "approved", "message": "Approved via signal"})
                            workflow.logger.info("Activity completed successfully")
                        except Exception as e:
                            workflow.logger.error(f"Error completing activity: {str(e)}")
                            # Try cancellation as a fallback
                            try:
                                workflow.logger.info("Trying to cancel the activity")
                                await activity_handle.cancel()
                                workflow.logger.info("Activity cancelled successfully")
                            except Exception as cancel_error:
                                workflow.logger.error(f"Error cancelling activity: {str(cancel_error)}")

                except asyncio.TimeoutError:
                    workflow.logger.info("Approval timeout reached")
                    # Wait for the activity to complete
                    approval_result = await activity_handle
                    workflow.logger.info(f"Activity completed with result: {approval_result}")

                # Process the approval result
                is_approved = False
                
                # First check if we have a decision from the signal
                if self._approval_received and self.approval_decision:
                    workflow.logger.info(f"Using decision from signal: {self.approval_decision}")
                    is_approved = self.approval_decision.lower() in ["approve", "approved"]
                # Then check the approval_result if we have one
                elif isinstance(approval_result, str):
                    # String format: "approve", "approved", "reject", "rejected"
                    workflow.logger.info(f"Using decision from string result: {approval_result}")
                    is_approved = approval_result.lower() in ["approve", "approved"]
                elif isinstance(approval_result, dict):
                    if "decision" in approval_result:
                        # Dict format: {"decision": "approve"} or {"decision": "reject"}
                        workflow.logger.info(f"Using decision from dict result: {approval_result}")
                        is_approved = approval_result["decision"].lower() in ["approve", "approved"]
                    elif "status" in approval_result:
                        # Dict format from activity: {"status": "completed", "message": "..."}
                        workflow.logger.info(f"Using status from dict result: {approval_result}")
                        is_approved = approval_result["status"].lower() in ["approved", "completed"]
                
                workflow.logger.info(f"Final approval decision: {is_approved}")

                if is_approved:
                    # If approved, complete the hotel booking
                    workflow.logger.info(f"Hotel booking approved: {book_input.book_hotel_id}")
                    hotel_result = await workflow.execute_activity(
                        complete_hotel_booking,
                        book_input,
                        start_to_close_timeout=timedelta(seconds=10),
                    )
                    results["booked_hotel"] = hotel_result
                    results["approval_status"] = "approved"
                else:
                    # If rejected, cancel the workflow
                    workflow.logger.info(f"Hotel booking rejected: {book_input.book_hotel_id}")
                    raise ValueError(f"Hotel booking rejected by human approver: {book_input.book_hotel_id}")
            else:
                # Normal hotel booking (no manual approval needed)
                results["booked_hotel"] = hotel_result

            # Book flight
            compensations.append(undo_book_flight)
            flight_result = await workflow.execute_activity(
                book_flight,
                book_input,
                start_to_close_timeout=timedelta(seconds=10),
                retry_policy=RetryPolicy(
                    initial_interval=timedelta(seconds=1),
                    maximum_interval=timedelta(seconds=1),
                ),
            )
            results["booked_flight"] = flight_result

            return {"status": "success", "message": results}

        except Exception as ex:
            for compensation in reversed(compensations):
                await workflow.execute_activity(
                    compensation,
                    book_input,
                    start_to_close_timeout=timedelta(seconds=10),
                )
            return {"status": "failure", "message": str(ex)}
