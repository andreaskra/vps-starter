// Chairside — interactivity hooks
(() => {
  // Sticky-header shadow on scroll
  const topbar = document.getElementById('topbar');
  if (topbar) {
    const onScroll = () => {
      topbar.classList.toggle('is-scrolled', window.scrollY > 8);
    };
    onScroll();
    window.addEventListener('scroll', onScroll, { passive: true });
  }

  // Smooth scroll for in-page anchors (respects reduced-motion)
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (!reduceMotion) {
    document.querySelectorAll('a[href^="#"]').forEach((a) => {
      a.addEventListener('click', (e) => {
        const id = a.getAttribute('href').slice(1);
        if (!id) return;
        const el = document.getElementById(id);
        if (!el) return;
        e.preventDefault();
        el.scrollIntoView({ behavior: 'smooth', block: 'start' });
        history.pushState(null, '', `#${id}`);
      });
    });
  }
})();
