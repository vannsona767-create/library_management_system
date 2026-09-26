// Library Management System - shared JS
document.addEventListener('DOMContentLoaded', () => {
    const track = document.querySelector('[data-book-slider-track]');
    if (!track) return;

    document.querySelectorAll('[data-book-slider]').forEach((button) => {
        button.addEventListener('click', () => {
            const direction = button.dataset.bookSlider === 'next' ? 1 : -1;
            const scrollAmount = Math.max(180, track.clientWidth * 0.75);
            const maxScroll = track.scrollWidth - track.clientWidth;
            const atStart = track.scrollLeft <= 4;
            const atEnd = track.scrollLeft >= maxScroll - 4;

            if (direction > 0 && atEnd) {
                track.scrollTo({
                    left: 0,
                    behavior: 'smooth',
                });
                return;
            }

            if (direction < 0 && atStart) {
                track.scrollTo({
                    left: maxScroll,
                    behavior: 'smooth',
                });
                return;
            }

            track.scrollBy({
                left: direction * scrollAmount,
                behavior: 'smooth',
            });
        });
    });
});
