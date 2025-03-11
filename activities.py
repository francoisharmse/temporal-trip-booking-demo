import asyncio
from temporalio import activity
from shared import BookVacationInput
import random


@activity.defn
async def book_hotel(book_input: BookVacationInput) -> dict:
    """
    Book a hotel.

    Args:
        book_input: Input data for booking a hotel.

    Returns:
        dict: Confirmation of the booking with status information.
    """
    print(f"Booking hotel: {book_input.book_hotel_id}")
    
    # Check if this is a manual booking that requires human approval
    if book_input.book_hotel_id.startswith("manual_"):
        print(f"Manual hotel booking detected: {book_input.book_hotel_id}")
        print(f"Scheduling human approval task for user: {book_input.book_user_id}")
        return {
            "booked_hotel": book_input.book_hotel_id,
            "status": "waiting_for_approval",
            "message": "manual_approval_needed",
            "user_id": book_input.book_user_id,
            "needs_approval": True,
            "manual_approval_needed": True
        }
    
    # Simulate a service outage for testing compensation
    # This will be retried based on the retry policy in the workflow
    if random.random() < 0.3:  # 30% chance of failure
        raise RuntimeError("Hotel service is down. Retrying...")
    
    # Simulate successful booking
    await asyncio.sleep(0.1)
    return {
        "booked_hotel": book_input.book_hotel_id,
        "status": "confirmed",
        "message": f"Booked hotel: {book_input.book_hotel_id}"
    }


@activity.defn
async def book_flight(book_input: BookVacationInput) -> str:
    """
    Book a flight.
    
    Args:
        book_input: Input data for booking a flight.
        
    Returns:
        str: Confirmation of the booking.
    """
    print(f"Booking flight: {book_input.book_flight_id}")
    
    # Simulate successful booking
    await asyncio.sleep(0.1)
    return f"Booked flight: {book_input.book_flight_id}"


@activity.defn
async def book_car(book_input: BookVacationInput) -> str:
    """
    Book a car.
    
    Args:
        book_input: Input data for booking a car.
        
    Returns:
        str: Confirmation of the booking.
    """
    print(f"Booking car: {book_input.book_car_id}")
    
    # Simulate successful booking
    await asyncio.sleep(0.1)
    return f"Booked car: {book_input.book_car_id}"


@activity.defn
async def wait_for_human_approval(book_input: BookVacationInput) -> dict:
    """
    Wait for human approval of a booking.
    
    This is a long-running activity that will be completed when a human approves or rejects the booking.
    The activity will be cancelled when the workflow receives an approval signal.
    
    Args:
        book_input: Input data for booking approval.
        
    Returns:
        dict: Result of the approval process.
    """
    print(f"Waiting for human approval for hotel: {book_input.book_hotel_id}")
    
    # Initial heartbeat with booking details
    # Add explicit flags to make it easier to detect this activity
    activity.heartbeat({
        "booking_id": book_input.book_hotel_id,
        "user_id": book_input.book_user_id,
        "status": "waiting_for_approval",
        "needs_approval": True,
        "manual_approval_needed": True
    })
    
    # This is a long-running activity that will be completed externally
    # We'll simulate the waiting with a loop that checks for cancellation
    try:
        # Keep the activity alive until it's cancelled
        count = 0
        while True:
            try:
                # Send a heartbeat every 5 seconds to reduce event frequency
                # Include the approval flags in every heartbeat
                if count % 5 == 0:
                    activity.heartbeat({
                        "booking_id": book_input.book_hotel_id,
                        "user_id": book_input.book_user_id,
                        "status": "waiting_for_approval",
                        "needs_approval": True,
                        "manual_approval_needed": True,
                        "heartbeat_count": count
                    })
                    print(f"Sent heartbeat {count} for booking: {book_input.book_hotel_id}")
                
                # Sleep for a short time - this will raise CancelledError when cancelled
                # Use a shorter sleep to be more responsive to cancellation
                await asyncio.sleep(0.5)
                count += 1
                
                # Timeout after 10 minutes (600 seconds) as a safety measure
                if count > 1200:  # 1200 * 0.5 = 600 seconds = 10 minutes
                    print(f"Approval timeout for booking: {book_input.book_hotel_id}")
                    return {
                        "status": "timeout",
                        "message": "Approval timed out after 10 minutes"
                    }
            except asyncio.CancelledError:
                # Handle cancellation from asyncio
                print(f"Activity received asyncio.CancelledError for booking: {book_input.book_hotel_id}")
                return {
                    "status": "approved",
                    "message": "Booking approved via cancellation"
                }
    except Exception as e:
        print(f"Error in wait_for_human_approval: {str(e)}")
        # Return a failure result instead of raising an exception
        return {
            "status": "error",
            "message": f"Error in approval process: {str(e)}"
        }
    
    # If we get here, the activity was cancelled, which means the booking was approved or rejected
    return {
        "status": "completed",
        "message": "Human approval process completed"
    }


@activity.defn
async def complete_hotel_booking(book_input: BookVacationInput) -> dict:
    """
    Complete a manual hotel booking after human approval.
    
    Args:
        book_input: Input data for booking a hotel.
        
    Returns:
        dict: Confirmation of the booking with status information.
    """
    print(f"Completing hotel booking after approval: {book_input.book_hotel_id}")
    
    # Simulate successful booking
    await asyncio.sleep(0.5)
    return {
        "booked_hotel": book_input.book_hotel_id,
        "status": "confirmed",
        "message": f"Booked hotel: {book_input.book_hotel_id} (after approval)",
        "approved": True
    }


@activity.defn
async def undo_book_car(book_input: BookVacationInput) -> str:
    """
    Cancel a car booking.
    
    Args:
        book_input: Input data for the booking to cancel.
        
    Returns:
        str: Confirmation of the cancellation.
    """
    print(f"Cancelling car booking: {book_input.book_car_id}")
    
    # Simulate cancellation
    await asyncio.sleep(0.1)
    return f"Cancelled car booking: {book_input.book_car_id}"


@activity.defn
async def undo_book_hotel(book_input: BookVacationInput) -> str:
    """
    Cancel a hotel booking.
    
    Args:
        book_input: Input data for the booking to cancel.
        
    Returns:
        str: Confirmation of the cancellation.
    """
    print(f"Cancelling hotel booking: {book_input.book_hotel_id}")
    
    # Simulate cancellation
    await asyncio.sleep(0.1)
    return f"Cancelled hotel booking: {book_input.book_hotel_id}"


@activity.defn
async def undo_book_flight(book_input: BookVacationInput) -> str:
    """
    Cancel a flight booking.
    
    Args:
        book_input: Input data for the booking to cancel.
        
    Returns:
        str: Confirmation of the cancellation.
    """
    print(f"Cancelling flight booking: {book_input.book_flight_id}")
    
    # Simulate cancellation
    await asyncio.sleep(0.1)
    return f"Cancelled flight booking: {book_input.book_flight_id}"
