(() => {
  const local = ["localhost", "127.0.0.1"].includes(window.location.hostname) && window.location.port === "8000";
  window.SCREENING_CONFIG = Object.freeze({
    API_BASE_URL: local ? "" : "https://somnisignal-screening-proxy.somnisignal-screening-proxy.workers.dev",
    LOCAL_DEMO_MODE: local,
    TURNSTILE_SITE_KEY: "0x4AAAAAAEDgexj-DrXRsEzW",
    ENABLE_RESEARCH_UPLOADS: true
  });
})();
