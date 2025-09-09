// Restaurant Management System - Main JavaScript

// Global variables
window.restaurantApp = {
    currentBranch: null,
    currentTable: null,
    cart: [],
    settings: {}
};

// Utility functions
function showAlert(message, type = 'info') {
    const alertDiv = document.createElement('div');
    alertDiv.className = `alert alert-${type} alert-dismissible fade show`;
    alertDiv.innerHTML = `
        ${message}
        <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
    `;
    
    const container = document.querySelector('.container') || document.body;
    container.insertBefore(alertDiv, container.firstChild);
    
    // Auto dismiss after 5 seconds
    setTimeout(() => {
        if (alertDiv.parentNode) {
            alertDiv.remove();
        }
    }, 5000);
}

function showLoading(show = true) {
    let loader = document.getElementById('loading-spinner');
    if (show) {
        if (!loader) {
            loader = document.createElement('div');
            loader.id = 'loading-spinner';
            loader.className = 'spinner';
            document.body.appendChild(loader);
        }
        loader.style.display = 'block';
    } else {
        if (loader) {
            loader.style.display = 'none';
        }
    }
}

// Confirmation dialog
async function showConfirm(message) {
    return new Promise((resolve) => {
        if (confirm(message)) {
            resolve(true);
        } else {
            resolve(false);
        }
    });
}

// API helper functions
async function apiCall(url, options = {}) {
    try {
        showLoading(true);
        const response = await fetch(url, {
            headers: {
                'Content-Type': 'application/json',
                ...options.headers
            },
            ...options
        });
        
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        
        const data = await response.json();
        return data;
    } catch (error) {
        console.error('API Error:', error);
        showAlert(`خطأ في الاتصال: ${error.message}`, 'danger');
        throw error;
    } finally {
        showLoading(false);
    }
}

// POS System functions
function addToCart(product) {
    const existingItem = window.restaurantApp.cart.find(item => item.id === product.id);
    
    if (existingItem) {
        existingItem.quantity += 1;
    } else {
        window.restaurantApp.cart.push({
            ...product,
            quantity: 1
        });
    }
    
    updateCartDisplay();
    showAlert(`تم إضافة ${product.name} إلى السلة`, 'success');
}

function removeFromCart(productId) {
    window.restaurantApp.cart = window.restaurantApp.cart.filter(item => item.id !== productId);
    updateCartDisplay();
    showAlert('تم حذف الصنف من السلة', 'info');
}

function updateCartDisplay() {
    const cartContainer = document.getElementById('cart-items');
    const totalContainer = document.getElementById('cart-total');
    
    if (!cartContainer) return;
    
    cartContainer.innerHTML = '';
    let total = 0;
    
    window.restaurantApp.cart.forEach(item => {
        const itemTotal = item.price * item.quantity;
        total += itemTotal;
        
        const itemDiv = document.createElement('div');
        itemDiv.className = 'invoice-item';
        itemDiv.innerHTML = `
            <div>
                <strong>${item.name}</strong><br>
                <small>${item.quantity} × ${item.price.toFixed(2)} ريال</small>
            </div>
            <div>
                <span class="me-2">${itemTotal.toFixed(2)} ريال</span>
                <button class="btn btn-sm btn-outline-danger" onclick="removeFromCart(${item.id})">
                    <i class="fas fa-trash"></i>
                </button>
            </div>
        `;
        cartContainer.appendChild(itemDiv);
    });
    
    if (totalContainer) {
        totalContainer.textContent = `${total.toFixed(2)} ريال`;
    }
}

// Table management functions
function selectTable(tableNumber, branchCode) {
    window.restaurantApp.currentTable = tableNumber;
    window.restaurantApp.currentBranch = branchCode;
    
    // Update UI to show selected table
    document.querySelectorAll('.table-card').forEach(card => {
        card.classList.remove('selected');
    });
    
    const selectedCard = document.querySelector(`[data-table="${tableNumber}"]`);
    if (selectedCard) {
        selectedCard.classList.add('selected');
    }
    
    showAlert(`تم اختيار الطاولة رقم ${tableNumber}`, 'success');
}

// Form validation
function validateForm(formOrId) {
    const form = (typeof formOrId === 'string') ? document.getElementById(formOrId) : formOrId;
    if (!form) return true; // لا تمنع الإرسال إذا لم نجد النموذج

    const requiredFields = form.querySelectorAll('[required]');
    let isValid = true;

    requiredFields.forEach(field => {
        if (!field.value || !field.value.toString().trim()) {
            field.classList.add('is-invalid');
            isValid = false;
        } else {
            field.classList.remove('is-invalid');
        }
    });

    return isValid;
}

// Print functions
function printInvoice(invoiceId) {
    const printWindow = window.open(`/print/invoice/${invoiceId}`, '_blank');
    printWindow.onload = function() {
        printWindow.print();
    };
}

function printReport() {
    window.print();
}

// Initialize app when DOM is loaded
document.addEventListener('DOMContentLoaded', function() {
    console.log('Restaurant Management System initialized');
    
    // Initialize tooltips if Bootstrap is available
    if (typeof bootstrap !== 'undefined') {
        const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
        tooltipTriggerList.map(function (tooltipTriggerEl) {
            return new bootstrap.Tooltip(tooltipTriggerEl);
        });
    }
    
    // Initialize any existing cart data
    updateCartDisplay();
    
    // Add click handlers for dashboard cards
    document.querySelectorAll('.dashboard-card').forEach(card => {
        card.addEventListener('click', function() {
            const link = this.closest('a');
            if (link) {
                window.location.href = link.href;
            }
        });
    });
    
    // Add form validation to all forms except login-form (server-side validates)
    document.querySelectorAll('form').forEach(form => {
        form.addEventListener('submit', function(e) {
            // Skip client-side block for login form to ensure POST reaches server
            if (this && (this.id === 'login-form' || this.dataset.skipValidation === '1')) { return; }
            if (!validateForm(this)) {
                e.preventDefault();
                showAlert('يرجى ملء جميع الحقول المطلوبة', 'warning');
            }
        });
    });
});

// Export functions for global use
window.showAlert = showAlert;
window.showConfirm = showConfirm;
window.apiCall = apiCall;
window.addToCart = addToCart;
window.removeFromCart = removeFromCart;
window.selectTable = selectTable;
window.printInvoice = printInvoice;
window.printReport = printReport;
