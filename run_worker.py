import asyncio

from temporalio.client import Client
from temporalio.worker import Worker

from activities import (
    book_car,
    book_flight,
    book_hotel,
    complete_hotel_booking,
    undo_book_car,
    undo_book_flight,
    undo_book_hotel,
    wait_for_human_approval,
)
from shared import TASK_QUEUE_NAME
from workflows import BookingWorkflow

interrupt_event = asyncio.Event()


async def main():
    """
    Main function to start the worker.
    """
    client = await Client.connect("localhost:7233")

    worker = Worker(
        client,
        task_queue=TASK_QUEUE_NAME,
        workflows=[BookingWorkflow],
        activities=[
            book_car,
            book_hotel,
            book_flight,
            undo_book_car,
            undo_book_hotel,
            undo_book_flight,
            wait_for_human_approval,
            complete_hotel_booking,
        ],
    )
    print("\nWorker started, ctrl+c to exit\n")
    await worker.run()
    try:
        await interrupt_event.wait()
    finally:
        print("\nShutting down the worker\n")


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        print("\nInterrupt received, shutting down...\n")
        interrupt_event.set()
        loop.run_until_complete(loop.shutdown_asyncgens())
