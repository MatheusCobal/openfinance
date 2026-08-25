// Presentational interactions for the public landing page.
(function () {
  'use strict';

  document.documentElement.classList.add('lp-js');

  var header = document.getElementById('lp-header');
  function syncHeader() {
    if (header) header.classList.toggle('lp-scrolled', window.scrollY > 8);
  }
  window.addEventListener('scroll', syncHeader, { passive: true });
  syncHeader();

  var reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var revealed = document.querySelectorAll('.lp-reveal');
  if (reduceMotion || !('IntersectionObserver' in window)) {
    revealed.forEach(function (element) {
      element.classList.add('lp-reveal-visible');
    });
  } else {
    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          entry.target.classList.add('lp-reveal-visible');
          observer.unobserve(entry.target);
        }
      });
    }, { threshold: 0.12, rootMargin: '0px 0px -40px 0px' });
    revealed.forEach(function (element) {
      observer.observe(element);
    });
  }

  var year = document.getElementById('lp-year');
  if (year) year.textContent = String(new Date().getFullYear());
})();
