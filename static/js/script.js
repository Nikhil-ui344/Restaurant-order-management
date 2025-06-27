document.addEventListener("DOMContentLoaded", function () {
    // Submit order handler
    const submitOrderBtn = document.getElementById("submit-order");
    if (submitOrderBtn) {
        submitOrderBtn.addEventListener("click", function () {
            fetch('/submit_order', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({}) // Empty body, assuming server uses session-based cart
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    alert("✅ Order placed successfully! Your order is being processed.");
                    if (document.getElementById("order-status")) {
                        document.getElementById("order-status").textContent = "Order Placed";
                    }
                    if (document.getElementById("estimated-time")) {
                        document.getElementById("estimated-time").textContent = `Estimated Time: ${data.estimated_time} mins`;
                    }
                    updateCartDisplay(); // Clear cart display after order
                } else {
                    alert(data.error || "⚠ Error submitting order. Please try again.");
                }
            })
            .catch(error => {
                console.error("🚨 Error submitting order:", error);
                alert("⚠ Error submitting order. Please try again.");
            });
        });
    }
});

function updateCartDisplay() {
    const cartList = document.getElementById("cart-items");
    const totalPriceElement = document.getElementById("total-price");
    if (!cartList || !totalPriceElement) return;

    // Fetch cart data from server to display
    fetch('/cart', {
        method: 'GET',
        headers: { 'Content-Type': 'application/json' }
    })
    .then(response => response.json())
    .then(data => {
        cartList.innerHTML = "";
        let totalPrice = 0;

        if (!data.cart_items || Object.keys(data.cart_items).length === 0) {
            cartList.innerHTML = "<p>🛒 Your cart is empty!</p>";
            totalPriceElement.textContent = "Total: ₹0";
            return;
        }

        Object.values(data.cart_items).forEach(item => {
            const listItem = document.createElement("li");
            listItem.className = "cart-item";
            listItem.innerHTML = `
                <span>${item.name} x ${item.quantity}</span>
                <span>₹${(item.price * item.quantity).toFixed(2)}</span>
            `;
            cartList.appendChild(listItem);
            totalPrice += item.price * item.quantity;
        });

        totalPriceElement.textContent = `Total: ₹${totalPrice.toFixed(2)}`;
    })
    .catch(error => {
        console.error("🚨 Error fetching cart:", error);
        cartList.innerHTML = "<p>⚠ Error loading cart!</p>";
        totalPriceElement.textContent = "Total: ₹0";
    });
}