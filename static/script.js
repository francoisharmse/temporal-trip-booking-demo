document.addEventListener('DOMContentLoaded', function() {
    const bookingForm = document.getElementById('bookingForm');
    const resultCard = document.getElementById('resultCard');
    const resultContent = document.getElementById('resultContent');
    const newBookingBtn = document.getElementById('newBookingBtn');
    const refreshImageBtn = document.getElementById('refreshImageBtn');
    const destinationImage = document.getElementById('destinationImage');

    // Array of Unsplash photo IDs for travel destinations
    const travelPhotoIds = [
        'photo-1476514525535-07fb3b4ae5f1', // Mountains
        'photo-1507525428034-b723cf961d3e', // Beach
        'photo-1520250497591-112f2f40a3f4', // City
        'photo-1530789253388-582c481c54b0', // Island
        'photo-1501785888041-af3ef285b470', // Landscape
        'photo-1530521954074-e64f6810b32d', // Resort
        'photo-1518548419970-58e3b4079ab2', // Tropical
        'photo-1504280390367-361c6d9f38f4', // Beach hut
        'photo-1551882547-ff40c63fe5fa', // Hotel
        'photo-1548574505-5e239809ee19', // Paris
        'photo-1534430480872-3498386e7856', // Sunset beach
        'photo-1553570739-330b8db8a925'  // Venice
    ];

    // Function to load a new random destination image
    function loadNewDestinationImage() {
        // Get a random photo ID from the array
        const randomIndex = Math.floor(Math.random() * travelPhotoIds.length);
        const photoId = travelPhotoIds[randomIndex];

        // Create the Unsplash URL with the photo ID
        const imageUrl = `https://images.unsplash.com/${photoId}?ixlib=rb-4.0.3&auto=format&fit=crop&w=1200&h=400&q=80`;

        // Show loading state
        destinationImage.style.opacity = '0.6';

        // Create a new image object to preload
        const newImage = new Image();
        newImage.onload = function() {
            destinationImage.src = imageUrl;
            destinationImage.style.opacity = '1';
        };
        newImage.src = imageUrl;
    }

    // Add click event for refresh image button
    refreshImageBtn.addEventListener('click', function(event) {
        event.preventDefault();
        loadNewDestinationImage();

        // Add rotation animation
        this.classList.add('rotating');
        setTimeout(() => {
            this.classList.remove('rotating');
        }, 500);
    });

    // Function to handle approval or rejection
    async function handleApprovalDecision(workflowId, decision) {
        try {
            const approvalBtn = document.getElementById('approveBtn');
            const rejectBtn = document.getElementById('rejectBtn');
            const approvalStatus = document.getElementById('approvalStatus');
            
            // Disable buttons during processing
            if (approvalBtn) approvalBtn.disabled = true;
            if (rejectBtn) rejectBtn.disabled = true;
            
            // Show processing message
            if (approvalStatus) {
                approvalStatus.innerHTML = `<p class="processing">Processing ${decision} request...</p>`;
            }
            
            console.log(`Sending approval request for workflow ${workflowId} with decision: ${decision}`);
            
            // Send approval decision to the server
            const response = await fetch('/approve-booking', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    workflow_id: workflowId,
                    decision: decision
                })
            });
            
            const data = await response.json();
            console.log(`Approval response:`, data);
            
            // Update the UI based on the response
            if (response.ok) {
                if (approvalStatus) {
                    approvalStatus.innerHTML = `
                        <p class="${decision === 'approve' ? 'success' : 'error'}">
                            Booking has been ${decision}d successfully.
                        </p>
                    `;
                }
                
                // Hide the approval buttons
                const approvalActions = document.getElementById('approvalActions');
                if (approvalActions) {
                    approvalActions.style.display = 'none';
                }
            } else {
                if (approvalStatus) {
                    approvalStatus.innerHTML = `
                        <p class="error">
                            Error: ${data.error || 'Failed to process your request'}
                        </p>
                    `;
                }
                
                // Re-enable buttons
                if (approvalBtn) approvalBtn.disabled = false;
                if (rejectBtn) rejectBtn.disabled = false;
            }
        } catch (error) {
            console.error('Error handling approval:', error);
            const approvalStatus = document.getElementById('approvalStatus');
            if (approvalStatus) {
                approvalStatus.innerHTML = `
                    <p class="error">
                        An unexpected error occurred. Please try again.
                    </p>
                `;
            }
            
            // Re-enable buttons
            const approvalBtn = document.getElementById('approveBtn');
            const rejectBtn = document.getElementById('rejectBtn');
            if (approvalBtn) approvalBtn.disabled = false;
            if (rejectBtn) rejectBtn.disabled = false;
        }
    }

    // Handle form submission
    bookingForm.addEventListener('submit', async function(event) {
        event.preventDefault();

        // Show loading state
        const submitBtn = bookingForm.querySelector('button[type="submit"]');
        const originalBtnText = submitBtn.textContent;
        submitBtn.textContent = 'Processing...';
        submitBtn.disabled = true;

        // Get form data
        const formData = {
            name: document.getElementById('name').value,
            attempts: document.getElementById('attempts').value,
            car: document.getElementById('car').value,
            hotel: document.getElementById('hotel').value,
            flight: document.getElementById('flight').value
        };

        try {
            // Check if this is a manual booking based on hotel ID
            const isManualHotel = formData.hotel.startsWith('manual');
            
            // Set a timeout to prevent the UI from being stuck if the request takes too long
            const timeoutPromise = new Promise((_, reject) => {
                setTimeout(() => {
                    reject(new Error('Request timeout - but your booking might still be processing'));
                }, 10000); // 10 seconds timeout
            });
            
            // Send API request with timeout
            const fetchPromise = fetch('/book', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(formData)
            });
            
            // Race between the fetch and the timeout
            const response = await Promise.race([fetchPromise, timeoutPromise]);
            
            // Parse response
            const data = await response.json();

            // Display result
            let resultHTML = '';

            if (response.ok) {
                // Check if this is a manual approval booking
                // Log the data for debugging
                console.log("Booking result data:", data);
                
                // Check for manual approval in different possible structures
                let needsManualApproval = false;
                let hotelId = '';
                
                // Case 1: Direct check from response status
                if (data.status === 'waiting_for_approval' || data.needs_approval === true) {
                    needsManualApproval = true;
                    hotelId = data.hotel_id || formData.hotel;
                }
                // Case 2: Check if hotel booking contains "manual_approval_needed"
                else if (data.result && typeof data.result === 'object') {
                    // If result has a message object with booked_hotel property
                    if (data.result.message && 
                        data.result.message.booked_hotel && 
                        typeof data.result.message.booked_hotel === 'string' && 
                        data.result.message.booked_hotel.includes('manual_approval_needed')) {
                        needsManualApproval = true;
                        hotelId = formData.hotel;
                    }
                    // If result has a direct booked_hotel property
                    else if (data.result.booked_hotel && 
                             typeof data.result.booked_hotel === 'string' && 
                             data.result.booked_hotel.includes('manual_approval_needed')) {
                        needsManualApproval = true;
                        hotelId = formData.hotel;
                    }
                    // Check in nested message structure
                    else if (data.result.message && 
                             typeof data.result.message === 'object' &&
                             data.result.message.booked_hotel && 
                             typeof data.result.message.booked_hotel === 'string' && 
                             data.result.message.booked_hotel.includes('manual_approval_needed')) {
                        needsManualApproval = true;
                        hotelId = formData.hotel;
                    }
                    // Check for status field
                    else if (data.result.status === 'waiting_for_approval' ||
                             (data.result.message && data.result.message.status === 'waiting_for_approval')) {
                        needsManualApproval = true;
                        hotelId = formData.hotel;
                    }
                }
                
                // Case 3: If the hotel ID itself contains "manual" (fallback)
                if (formData.hotel && formData.hotel.startsWith('manual')) {
                    needsManualApproval = true;
                    hotelId = formData.hotel;
                }
                
                if (needsManualApproval) {
                    resultHTML += `<div class="success manual-approval-banner">
                        <h3>Booking Initiated - Manual Approval Required</h3>
                        <p><strong>User ID:</strong> ${data.user_id}</p>
                        <p><strong>Status:</strong> <span class="status-waiting">Waiting for Approval</span></p>
                    </div>`;
                    
                    // Add a note about the manual approval process
                    resultHTML += `<div class="manual-approval-info">
                        <p>Your booking for hotel <strong>${hotelId}</strong> requires manual approval.</p>
                        <p>You can check the status of your booking on the <a href="/approval-form">Pending Approvals</a> page.</p>
                        <p>Once approved, your booking will be completed automatically.</p>
                    </div>`;
                } else {
                    resultHTML += `<div class="success">
                        <h3>Booking Successful!</h3>
                        <p><strong>User ID:</strong> ${data.user_id}</p>
                        <p><strong>Status:</strong> <span class="status-complete">Complete</span></p>
                    </div>`;
                }
                
                // Format the result object
                resultHTML += `<div class="result-details">
                    <h4>Booking Details:</h4>
                    <pre>${JSON.stringify(data.result, null, 2)}</pre>
                </div>`;
            } else {
                resultHTML += `<div class="error">
                    <h3>Booking Failed</h3>
                    <p>${data.message || 'An error occurred during booking.'}</p>
                </div>`;
            }

            resultContent.innerHTML = resultHTML;

            // Hide form, show result
            bookingForm.parentElement.classList.add('hidden');
            resultCard.classList.remove('hidden');
            
            // Add event listeners to approval buttons if they exist
            const approveBtn = document.getElementById('approveBtn');
            const rejectBtn = document.getElementById('rejectBtn');
            
            if (approveBtn) {
                approveBtn.addEventListener('click', function() {
                    handleApprovalDecision(data.workflow_id, 'approve');
                });
            }
            
            if (rejectBtn) {
                rejectBtn.addEventListener('click', function() {
                    handleApprovalDecision(data.workflow_id, 'reject');
                });
            }
        } catch (error) {
            console.error('Error:', error);
            
            // Check if this is a timeout for a manual booking
            if (error.message.includes('timeout') && formData.hotel.startsWith('manual')) {
                resultHTML = `
                    <div class="success manual-approval-banner">
                        <h3>Booking Initiated - Manual Approval Required</h3>
                        <p><strong>User ID:</strong> ${formData.name}-XXXX (ID being generated)</p>
                        <p><strong>Status:</strong> <span class="status-waiting">Processing</span></p>
                    </div>
                    
                    <div class="manual-approval-info">
                        <p>Your booking for hotel <strong>${formData.hotel}</strong> requires manual approval.</p>
                        <p>The booking is still being processed. Please check the <a href="/approval-form">Pending Approvals</a> page in a few moments.</p>
                        <p>The server is taking longer than expected to respond, but your booking is likely still being processed.</p>
                    </div>
                `;
            } else {
                resultHTML = `
                    <div class="error">
                        <h3>Error</h3>
                        <p>An unexpected error occurred: ${error.message}</p>
                    </div>
                `;
            }
            
            resultContent.innerHTML = resultHTML;

            // Hide form, show result
            bookingForm.parentElement.classList.add('hidden');
            resultCard.classList.remove('hidden');
        } finally {
            // Always reset the button text and enable it
            submitBtn.textContent = originalBtnText;
            submitBtn.disabled = false;
        }
    });

    // Handle "New Booking" button click
    newBookingBtn.addEventListener('click', function() {
        // Reset form
        bookingForm.reset();

        // Show form, hide result
        bookingForm.parentElement.classList.remove('hidden');
        resultCard.classList.add('hidden');
    });
});
