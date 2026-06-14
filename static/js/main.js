/* 27c.site - Main JavaScript */

// Auto-dismiss flash messages after 5 seconds
document.addEventListener('DOMContentLoaded', function() {
    const flashes = document.querySelectorAll('.flash');
    flashes.forEach(function(flash) {
        setTimeout(function() {
            flash.style.transition = 'opacity 0.3s';
            flash.style.opacity = '0';
            setTimeout(function() { flash.remove(); }, 300);
        }, 5000);
    });

    // Close mobile nav when clicking a link
    const navLinks = document.querySelector('.nav-links');
    if (navLinks) {
        navLinks.querySelectorAll('a').forEach(function(link) {
            link.addEventListener('click', function() {
                navLinks.classList.remove('open');
            });
        });
    }

    // Close mobile nav when clicking outside
    document.addEventListener('click', function(e) {
        if (navLinks && !navLinks.contains(e.target) && !e.target.classList.contains('nav-toggle')) {
            navLinks.classList.remove('open');
        }
    });
});
