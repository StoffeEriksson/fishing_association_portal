(function () {
  'use strict';

  var STORAGE_KEY = 'portalSidebarCollapsed';
  var layout = document.getElementById('portal-layout');
  if (!layout) return;

  function desktopMatches() {
    return window.matchMedia('(min-width: 992px)').matches;
  }

  function syncToggleTab() {
    var tab = layout.querySelector('.sidebar-toggle-tab');
    if (!tab) return;
    var collapsed = layout.classList.contains('sidebar-collapsed');
    tab.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
    tab.setAttribute('aria-label', collapsed ? 'Öppna meny' : 'Stäng meny');
  }

  function applyCollapsedFromStorage() {
    if (!desktopMatches()) {
      layout.classList.remove('sidebar-collapsed');
      syncToggleTab();
      return;
    }
    try {
      layout.classList.toggle('sidebar-collapsed', localStorage.getItem(STORAGE_KEY) === '1');
    } catch (e) {}
    syncToggleTab();
  }

  function toggleSidebar() {
    if (!desktopMatches()) return;
    var next = !layout.classList.contains('sidebar-collapsed');
    layout.classList.toggle('sidebar-collapsed', next);
    try {
      localStorage.setItem(STORAGE_KEY, next ? '1' : '0');
    } catch (e) {}
    syncToggleTab();
  }

  document.addEventListener('DOMContentLoaded', function () {
    var tab = layout.querySelector('.sidebar-toggle-tab');
    if (tab) {
      syncToggleTab();
      tab.addEventListener('click', toggleSidebar);
    }
  });

  var mq = window.matchMedia('(min-width: 992px)');
  function onMqChange() {
    applyCollapsedFromStorage();
  }
  if (mq.addEventListener) {
    mq.addEventListener('change', onMqChange);
  } else if (mq.addListener) {
    mq.addListener(onMqChange);
  }
})();
