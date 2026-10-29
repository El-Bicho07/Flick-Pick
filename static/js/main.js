/**
 * FlickPick — Main Frontend JavaScript
 * Modern Web Guidance compliant: Form accessibility & user-invalid sync,
 * interaction fallbacks, clipboard utilities, and dynamic room controls.
 */

document.addEventListener('DOMContentLoaded', () => {
  // 1. Mobile Navigation Toggle & Accessible Drawer
  const navBtn = document.getElementById('mobile-nav-toggle') || document.querySelector('.mobile-nav-btn');
  const navDrawer = document.getElementById('mobile-nav-drawer') || document.querySelector('.nav-links');
  const navIcon = navBtn ? navBtn.querySelector('.material-symbols-outlined') : null;

  if (navBtn && navDrawer) {
    const toggleNav = (forceState) => {
      const isCurrentlyOpen = navDrawer.classList.contains('open') && !navDrawer.classList.contains('hidden');
      const shouldOpen = typeof forceState === 'boolean' ? forceState : !isCurrentlyOpen;

      if (shouldOpen) {
        navDrawer.classList.remove('hidden');
        navDrawer.classList.add('open');
        navBtn.setAttribute('aria-expanded', 'true');
        if (navIcon) navIcon.textContent = 'close';
      } else {
        navDrawer.classList.add('hidden');
        navDrawer.classList.remove('open');
        navBtn.setAttribute('aria-expanded', 'false');
        if (navIcon) navIcon.textContent = 'menu';
      }
    };

    navBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      toggleNav();
    });

    // Close when a link inside mobile drawer is clicked
    navDrawer.querySelectorAll('a').forEach(link => {
      link.addEventListener('click', () => toggleNav(false));
    });

    // Close on Escape key press without trapping focus
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && (navDrawer.classList.contains('open') || !navDrawer.classList.contains('hidden'))) {
        toggleNav(false);
        navBtn.focus();
      }
    });

    // Close when clicking outside header / drawer
    document.addEventListener('click', (e) => {
      if (navDrawer.classList.contains('open') && !navDrawer.classList.contains('hidden')) {
        const header = navBtn.closest('header');
        if (header && !header.contains(e.target)) {
          toggleNav(false);
        }
      }
    });
  }

  // 2. Room Code Copy Button
  const copyBtn = document.getElementById('copy-room-code-btn');
  if (copyBtn) {
    copyBtn.addEventListener('click', async () => {
      const code = copyBtn.getAttribute('data-code');
      if (!code) return;

      try {
        if (navigator.clipboard && window.isSecureContext) {
          await navigator.clipboard.writeText(code);
        } else {
          // Fallback textarea copy
          const temp = document.createElement('textarea');
          temp.value = code;
          document.body.appendChild(temp);
          temp.select();
          document.execCommand('copy');
          document.body.removeChild(temp);
        }

        const originalText = copyBtn.innerText;
        copyBtn.innerText = 'Copied!';
        copyBtn.classList.add('copied');
        setTimeout(() => {
          copyBtn.innerText = originalText;
          copyBtn.classList.remove('copied');
        }, 2000);
      } catch (err) {
        console.error('Failed to copy room code:', err);
      }
    });
  }

  // 3. Alert Auto-Dismiss and Close Buttons
  document.querySelectorAll('.alert-close').forEach(btn => {
    btn.addEventListener('click', () => {
      const alert = btn.closest('.alert');
      if (alert) {
        alert.style.opacity = '0';
        alert.style.transform = 'translateY(-10px)';
        setTimeout(() => alert.remove(), 250);
      }
    });
  });

  // 4. Modern Web Guidance: Synchronize aria-invalid with CSS :user-invalid state
  const syncAria = (el) => {
    if (!el || typeof el.getAttribute !== 'function') return;
    if (el.matches && el.matches(':user-invalid')) {
      el.setAttribute('aria-invalid', 'true');
    } else if (el.hasAttribute('aria-invalid')) {
      el.removeAttribute('aria-invalid');
    }
  };

  document.addEventListener('blur', (e) => syncAria(e.target), true);
  document.addEventListener('input', (e) => {
    if (e.target.hasAttribute && e.target.hasAttribute('aria-invalid')) {
      syncAria(e.target);
    }
  });

  // 5. Voting Candidate Selection Enhancement
  const votingCards = document.querySelectorAll('.voting-option-label');
  votingCards.forEach(label => {
    label.addEventListener('click', () => {
      const radio = label.querySelector('input[type="radio"]');
      if (radio) {
        radio.checked = true;
      }
    });
  });
});
