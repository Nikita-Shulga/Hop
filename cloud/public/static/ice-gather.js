// Legacy desktop clients consume one complete offer: never silently send a partial candidate list.
(function (root) {
  'use strict';
  function waitForGathering(pc, timeoutMs) {
    return new Promise(function (resolve, reject) {
      var timer = null, done = false;
      function finish(error) {
        if (done) return;
        done = true;
        clearTimeout(timer);
        pc.removeEventListener('icegatheringstatechange', changed);
        pc.removeEventListener('connectionstatechange', changed);
        if (error) reject(error); else resolve();
      }
      function changed() {
        if (pc.connectionState === 'closed') {
          var error = new Error('Connection closed'); error.code = 'ICE_CLOSED'; finish(error);
        } else if (pc.iceGatheringState === 'complete') finish();
      }
      pc.addEventListener('icegatheringstatechange', changed);
      pc.addEventListener('connectionstatechange', changed);
      timer = setTimeout(function () {
        var error = new Error('Network route gathering timed out'); error.code = 'ICE_GATHERING_TIMEOUT';
        finish(error);
      }, timeoutMs || 45000);
      changed(); // Also handles completion between reading state and subscribing.
    });
  }
  if (typeof module !== 'undefined' && module.exports) module.exports = { waitForGathering: waitForGathering };
  else root.HopIce = { waitForGathering: waitForGathering };
})(typeof window === 'undefined' ? globalThis : window);
