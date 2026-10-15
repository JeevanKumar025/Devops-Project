// AI assistance: This navigation interaction was drafted with OpenAI Codex.
const toggle = document.querySelector(".nav-toggle");
const navLinks = document.querySelector(".nav-links");

if (toggle && navLinks) {
    toggle.addEventListener("click", () => {
        const open = navLinks.classList.toggle("is-open");
        toggle.setAttribute("aria-expanded", open);
    });
}

// Ask for a confirmation only on actions that declare a confirmation message.
document.querySelectorAll("form[data-confirm]").forEach((form) => {
    form.addEventListener("submit", (event) => {
        if (!window.confirm(form.dataset.confirm)) {
            event.preventDefault();
        }
    });
});

// Replace compact data-lucide placeholders with consistent open-source SVGs.
if (window.lucide) {
    window.lucide.createIcons({ attrs: { "stroke-width": 1.8 } });
}

// Reveal content as it enters the viewport, without making any core function
// depend on JavaScript.
const revealItems = document.querySelectorAll(
    ".section, .menu-section, .cart-page, .checkout-page, .dashboard-page, .orders-page, .order-detail-page, .profile-page, .admin-page"
);

if ("IntersectionObserver" in window) {
    const observer = new IntersectionObserver((entries) => {
        entries.forEach((entry) => {
            if (entry.isIntersecting) {
                entry.target.classList.add("is-visible");
                observer.unobserve(entry.target);
            }
        });
    }, { threshold: 0.08 });

    revealItems.forEach((item) => {
        item.dataset.reveal = "";
        observer.observe(item);
    });
}

// Provide quick feedback before forms navigate to the next server-rendered page.
document.querySelectorAll("form[method='post'] button[type='submit']").forEach((button) => {
    button.addEventListener("click", () => {
        if (button.closest("form")?.checkValidity()) {
            button.classList.add("is-loading");
        }
    });
});

document.querySelectorAll("form[action*='/cart/add/']").forEach((form) => {
    form.addEventListener("submit", () => {
        const cartLink = [...document.querySelectorAll(".nav-links a")]
            .find((link) => link.textContent.trim().startsWith("Cart"));
        cartLink?.classList.add("cart-bump");
    });
});
