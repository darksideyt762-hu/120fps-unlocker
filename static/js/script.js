document.addEventListener('DOMContentLoaded', function() {
    const deviceModelInput = document.getElementById('deviceModel');
    const processBtn = document.getElementById('processBtn');
    const progressContainer = document.getElementById('progressContainer');
    const progressBar = document.getElementById('progressBar');
    const progressStatus = document.getElementById('progressStatus');
    const downloadSection = document.getElementById('downloadSection');
    const downloadLink = document.getElementById('downloadLink');
    const exampleChips = document.querySelectorAll('.example-chip');
    const notificationContainer = document.getElementById('notificationContainer');
    
    let currentJobId = null;
    let statusCheckInterval = null;
    
    // Example chips functionality
    exampleChips.forEach(chip => {
        chip.addEventListener('click', function() {
            deviceModelInput.value = this.getAttribute('data-model');
            showNotification('Device model set to ' + this.getAttribute('data-model'), 'info');
        });
    });
    
    // Process button functionality
    processBtn.addEventListener('click', function() {
        const deviceModel = deviceModelInput.value.trim().toUpperCase();
        
        if (!deviceModel) {
            showNotification('Please enter a device model', 'error');
            return;
        }
        
        if (deviceModel.length < 5 || deviceModel.length > 20) {
            showNotification('Device model should be between 5-20 characters', 'error');
            return;
        }
        
        // Start processing
        startProcessing(deviceModel);
    });
    
    function startProcessing(deviceModel) {
        // Reset UI
        progressContainer.style.display = 'block';
        downloadSection.style.display = 'none';
        processBtn.disabled = true;
        
        // Reset progress
        progressBar.style.width = '0%';
        resetSteps();
        
        // Show initial notification
        showNotification(`Starting processing for ${deviceModel}`, 'info');
        
        // Send request to backend
        fetch('/start_processing', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ device_name: deviceModel })
        })
        .then(response => response.json())
        .then(data => {
            if (data.error) {
                showNotification(data.error, 'error');
                processBtn.disabled = false;
                progressContainer.style.display = 'none';
                return;
            }
            
            currentJobId = data.job_id;
            // Start checking status
            statusCheckInterval = setInterval(checkStatus, 1000);
        })
        .catch(error => {
            showNotification('Failed to start processing: ' + error, 'error');
            processBtn.disabled = false;
            progressContainer.style.display = 'none';
        });
    }
    
    function checkStatus() {
        if (!currentJobId) return;
        
        fetch(`/status/${currentJobId}`)
            .then(response => response.json())
            .then(status => {
                // Update progress bar
                progressBar.style.width = status.progress + '%';
                progressStatus.textContent = status.status;
                
                // Update steps based on progress
                updateSteps(status.progress);
                
                if (status.progress === 100) {
                    // Processing complete
                    clearInterval(statusCheckInterval);
                    progressContainer.style.display = 'none';
                    downloadSection.style.display = 'block';
                    processBtn.disabled = false;
                    
                    // Set download link
                    if (status.download_url) {
                        downloadLink.href = status.download_url.replace('/download/', '/download_file/');
                        downloadLink.download = status.filename;
                    }
                    
                    showNotification('120FPS file generated successfully!', 'success');
                } else if (status.progress === 0 && status.status.includes('Failed') || status.status.includes('Error')) {
                    // Processing failed
                    clearInterval(statusCheckInterval);
                    processBtn.disabled = false;
                    showNotification(status.status, 'error');
                }
            })
            .catch(error => {
                console.error('Error checking status:', error);
            });
    }
    
    function updateSteps(progress) {
        // Reset all steps
        resetSteps();
        
        // Activate steps based on progress
        if (progress >= 20) document.getElementById('step1').classList.add('active');
        if (progress >= 40) document.getElementById('step2').classList.add('active');
        if (progress >= 60) document.getElementById('step3').classList.add('active');
        if (progress >= 80) document.getElementById('step4').classList.add('active');
        if (progress >= 100) document.getElementById('step5').classList.add('active');
    }
    
    function resetSteps() {
        for (let i = 1; i <= 5; i++) {
            document.getElementById(`step${i}`).classList.remove('active');
        }
        document.getElementById('step1').classList.add('active');
    }
    
    function showNotification(message, type = 'info') {
        const notification = document.createElement('div');
        notification.className = `notification ${type}`;
        
        let icon = 'info-circle';
        if (type === 'success') icon = 'check-circle';
        if (type === 'warning') icon = 'exclamation-triangle';
        if (type === 'error') icon = 'exclamation-circle';
        
        notification.innerHTML = `
            <i class="fas fa-${icon}"></i>
            <div>${message}</div>
        `;
        
        notificationContainer.appendChild(notification);
        
        // Trigger animation
        setTimeout(() => {
            notification.classList.add('show');
        }, 10);
        
        // Auto remove after 5 seconds
        setTimeout(() => {
            notification.classList.remove('show');
            setTimeout(() => {
                if (notification.parentNode) {
                    notification.parentNode.removeChild(notification);
                }
            }, 500);
        }, 5000);
    }
});