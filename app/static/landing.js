// OpenFinance — public landing page interactions.
// Strictly presentational: this file must NEVER call any API endpoint.
// A request to a protected route could trigger an auth redirect or API 401 on
// the public page when login is enabled (see tests/test_pages.py).

(function () {
  'use strict';

  // Enable the JS-only hidden state for scroll-reveal elements. Without this
  // class the CSS keeps everything visible (no-JS fallback).
  document.documentElement.classList.add('lp-js');

  // ── Header: solid background after scrolling past the top ──────────────
  var header = document.getElementById('lp-header');
  function syncHeader() {
    if (!header) return;
    header.classList.toggle('lp-scrolled', window.scrollY > 8);
  }
  window.addEventListener('scroll', syncHeader, { passive: true });
  syncHeader();

  // ── Mobile menu toggle ──────────────────────────────────────────────────
  var menuBtn = document.getElementById('lp-menu-btn');
  var mobileMenu = document.getElementById('lp-mobile-menu');
  if (menuBtn && mobileMenu) {
    menuBtn.addEventListener('click', function () {
      var open = mobileMenu.classList.toggle('hidden') === false;
      menuBtn.setAttribute('aria-expanded', String(open));
      menuBtn.setAttribute('aria-label', open ? 'Fechar menu' : 'Abrir menu');
    });
    // Close the menu after navigating to an anchor.
    mobileMenu.querySelectorAll('a').forEach(function (link) {
      link.addEventListener('click', function () {
        mobileMenu.classList.add('hidden');
        menuBtn.setAttribute('aria-expanded', 'false');
      });
    });
  }

  // ── Scroll-reveal animations ────────────────────────────────────────────
  var reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var revealed = document.querySelectorAll('.lp-reveal');
  if (reduceMotion || !('IntersectionObserver' in window)) {
    revealed.forEach(function (el) { el.classList.add('lp-reveal-visible'); });
  } else {
    var observer = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            entry.target.classList.add('lp-reveal-visible');
            observer.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.12, rootMargin: '0px 0px -40px 0px' }
    );
    revealed.forEach(function (el) { observer.observe(el); });
  }

  // ── Footer year ─────────────────────────────────────────────────────────
  var yearEl = document.getElementById('lp-year');
  if (yearEl) yearEl.textContent = String(new Date().getFullYear());
})();
