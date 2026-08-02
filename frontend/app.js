(() => {
  "use strict";

  const config = window.SCREENING_CONFIG || {};
  const baseUrl = String(config.API_BASE_URL || "").replace(/\/$/, "");
  const localPrefix = config.LOCAL_DEMO_MODE ? "/local" : "";
  const uploadPanel = document.querySelector("#upload-panel");
  const uploadForm = document.querySelector("#upload-form");
  const uploadButton = document.querySelector("#run-upload");
  const uploadMessage = document.querySelector("#upload-message");
  const serviceStatus = document.querySelector("#service-status");
  const analysisLive = document.querySelector("#analysis-live");
  const analysisStage = document.querySelector("#analysis-stage");
  const analysisDetail = document.querySelector("#analysis-detail");
  const analysisElapsed = document.querySelector("#analysis-elapsed");
  let turnstileToken = "";
  let elapsedTimer = null;
  let stageTimer = null;

  const analysisStages = [
    ["Securing the ECG record", "Reading the file without storing it permanently"],
    ["Checking signal quality", "Validating duration, sample rate, gaps, and clipping"],
    ["Detecting heartbeats", "Finding QRS peaks and calculating beat-to-beat intervals"],
    ["Measuring overnight patterns", "Extracting heart-rate variability from overlapping windows"],
    ["Preparing the screening result", "Combining the model estimates into a nightly summary"]
  ];

  const interpretations = {
    elevated_risk: {
      symbol: "↑",
      title: "Sleep Apnea Risk Prediction: Elevated Risk",
      explanation: "SomniSignal identified an elevated level of sleep-apnea-associated cardiac patterns in this recording. The result meets the model's elevated-risk criteria.",
      next: "Recommended next step: discuss symptoms and formal polysomnography or home sleep-apnea testing with a qualified clinician."
    },
    low_risk: {
      symbol: "✓",
      title: "Sleep Apnea Risk Prediction: Lower Risk",
      explanation: "SomniSignal identified a lower level of sleep-apnea-associated cardiac patterns in this recording. The result does not meet the model's elevated-risk criteria.",
      next: "Recommended next step: if symptoms such as loud snoring, witnessed breathing pauses, or daytime sleepiness remain, seek clinical evaluation."
    },
    inconclusive: {
      symbol: "!",
      title: "Sleep Apnea Risk Prediction: Unavailable",
      explanation: "SomniSignal could not produce a valid risk prediction because the recording failed the required signal-quality checks.",
      next: "Recommended next step: use a better-quality overnight ECG or seek a validated clinical sleep test."
    }
  };

  function endpoint(path) {
    return `${baseUrl}${localPrefix}${path}`;
  }

  function setService(text, state) {
    serviceStatus.innerHTML = "";
    const dot = document.createElement("i");
    serviceStatus.append(dot, document.createTextNode(text));
    serviceStatus.className = `service-status ${state}`;
  }

  async function checkHealth() {
    if (!config.LOCAL_DEMO_MODE && !config.ENABLE_RESEARCH_UPLOADS) {
      setService("research access pending", "offline");
      uploadButton.disabled = true;
      uploadMessage.textContent = "The hosted research screening connection is not open yet";
      return;
    }
    if (!config.LOCAL_DEMO_MODE && (!baseUrl || baseUrl.includes("example.workers.dev"))) {
      setService("connection not configured", "offline");
      uploadButton.disabled = true;
      uploadMessage.textContent = "The hosted screening connection is not configured yet";
      return;
    }
    try {
      const response = await fetch(`${baseUrl}/health`, { cache: "no-store" });
      if (!response.ok) throw new Error("offline");
      const health = await response.json();
      if (!health.model_ready) throw new Error("model unavailable");
      if (!config.LOCAL_DEMO_MODE && !health.research_demo_uploads_enabled) {
        setService("research access pending", "offline");
        uploadButton.disabled = true;
        uploadMessage.textContent = "Public research uploads are not yet open";
        return;
      }
      setService("screening service online", "online");
    } catch {
      setService("temporarily offline", "offline");
      uploadButton.disabled = true;
      uploadMessage.textContent = "Screening service temporarily offline";
    }
  }

  function mountTurnstile() {
    if (config.LOCAL_DEMO_MODE || !config.TURNSTILE_SITE_KEY || !window.turnstile) return;
    window.turnstile.render("#turnstile-container", {
      sitekey: config.TURNSTILE_SITE_KEY,
      action: "research_upload",
      callback: (token) => { turnstileToken = token; },
      "expired-callback": () => { turnstileToken = ""; },
      "error-callback": () => { turnstileToken = ""; }
    });
  }

  function startLiveAnalysis() {
    let stageIndex = 0;
    const startedAt = Date.now();
    analysisLive.hidden = false;
    uploadPanel.classList.add("is-analyzing");
    analysisStage.textContent = analysisStages[0][0];
    analysisDetail.textContent = analysisStages[0][1];
    analysisElapsed.textContent = "00:00";

    elapsedTimer = window.setInterval(() => {
      const totalSeconds = Math.floor((Date.now() - startedAt) / 1000);
      const minutes = String(Math.floor(totalSeconds / 60)).padStart(2, "0");
      const seconds = String(totalSeconds % 60).padStart(2, "0");
      analysisElapsed.textContent = `${minutes}:${seconds}`;
    }, 1000);

    stageTimer = window.setInterval(() => {
      stageIndex = Math.min(stageIndex + 1, analysisStages.length - 1);
      analysisStage.textContent = analysisStages[stageIndex][0];
      analysisDetail.textContent = analysisStages[stageIndex][1];
    }, 2800);
  }

  function stopLiveAnalysis(success) {
    window.clearInterval(elapsedTimer);
    window.clearInterval(stageTimer);
    uploadPanel.classList.remove("is-analyzing");
    if (success) {
      analysisStage.textContent = "Analysis complete";
      analysisDetail.textContent = "The temporary ECG data has been deleted";
      window.setTimeout(() => { analysisLive.hidden = true; }, 700);
    } else {
      analysisStage.textContent = "Analysis stopped safely";
      analysisDetail.textContent = "Review the message above and try again";
    }
  }

  async function waitForResult(statusUrl) {
    for (let attempt = 0; attempt < 90; attempt += 1) {
      const response = await fetch(endpoint(statusUrl), { cache: "no-store" });
      if (!response.ok) throw new Error("Screening job expired or could not be found");
      const job = await response.json();
      if (job.status === "completed") return job.result;
      if (job.status === "failed") throw new Error(job.error || "Screening failed safely");
      uploadMessage.textContent = job.status === "running" ? "Analyzing the ECG now..." : "Waiting for the analysis engine...";
      await new Promise((resolve) => setTimeout(resolve, 700));
    }
    throw new Error("Screening timed out; no result was stored");
  }

  async function errorMessage(response, fallback) {
    try {
      const payload = await response.json();
      return typeof payload.detail === "string" ? payload.detail : fallback;
    } catch {
      return fallback;
    }
  }

  function showResult(result) {
    const content = document.querySelector("#result-content");
    const score = result.risk_score == null ? null : Math.round(result.risk_score * 100);
    const hasDirectionalEstimate = result.outcome === "inconclusive"
      && result.signal_quality !== "fail"
      && score != null;
    const displayOutcome = hasDirectionalEstimate
      ? (score >= 50 ? "elevated_risk" : "low_risk")
      : result.outcome;
    const interpretation = interpretations[displayOutcome] || interpretations.inconclusive;
    const outcomeLabels = {
      elevated_risk: "elevated risk",
      low_risk: "lower risk",
      inconclusive: "result unavailable"
    };
    const qualityLabels = {
      pass: "good",
      warn: "usable with caution",
      fail: "unusable"
    };
    content.hidden = false;
    content.dataset.outcome = displayOutcome;

    const outcome = document.querySelector("#result-outcome");
    outcome.textContent = outcomeLabels[displayOutcome] || "result unavailable";
    outcome.className = `outcome ${displayOutcome}`;
    document.querySelector("#result-symbol").textContent = interpretation.symbol;
    document.querySelector("#result-title").textContent = interpretation.title;
    document.querySelector("#result-explanation").textContent = interpretation.explanation;
    document.querySelector("#result-next-step").textContent = interpretation.next;

    document.querySelector("#risk-score").textContent = score == null ? "n/a" : `${score}%`;
    document.querySelector("#risk-meter").style.width = score == null ? "0" : `${score}%`;
    document.querySelector("#analyzed-minutes").textContent = result.analyzed_minutes;
    document.querySelector("#apnea-minutes").textContent = result.estimated_apnea_minutes ?? "n/a";
    document.querySelector("#signal-quality").textContent = qualityLabels[result.signal_quality] || "unavailable";
    document.querySelector("#result-disclaimer").textContent = result.disclaimer;
    content.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  uploadForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!config.LOCAL_DEMO_MODE && (
      !config.ENABLE_RESEARCH_UPLOADS ||
      !baseUrl ||
      baseUrl.includes("example.workers.dev") ||
      !config.TURNSTILE_SITE_KEY
    )) {
      uploadMessage.textContent = "Configure the hosted screening connection first";
      return;
    }
    if (!config.LOCAL_DEMO_MODE && !turnstileToken) {
      uploadMessage.textContent = "Complete human verification first";
      return;
    }

    const consent = uploadForm.elements.screening_consent.checked;
    if (!consent) {
      uploadMessage.textContent = "Confirm the consent statement first";
      return;
    }

    uploadButton.disabled = true;
    uploadMessage.textContent = "Uploading the ECG...";
    document.querySelector("#result-content").hidden = true;
    startLiveAnalysis();

    const body = new FormData(uploadForm);
    body.delete("screening_consent");
    body.set("adult_confirmed", "true");
    body.set("research_consent", "true");
    body.set("data_use_authorized", "true");

    try {
      const requestPath = config.LOCAL_DEMO_MODE
        ? "/v1/test-predictions"
        : "/v1/research-predictions";
      const response = await fetch(endpoint(requestPath), {
        method: "POST",
        headers: turnstileToken ? { "X-Turnstile-Token": turnstileToken } : undefined,
        body
      });
      if (response.status === 503) throw new Error("Screening service temporarily offline");
      if (response.status === 429) throw new Error("The service is busy; please try again shortly");
      if (!response.ok) throw new Error(await errorMessage(response, "The ECG upload was not accepted"));

      const accepted = await response.json();
      const result = await waitForResult(accepted.status_url);
      stopLiveAnalysis(true);
      showResult(result);
      uploadMessage.textContent = "Complete — raw ECG deleted — research result ready";
    } catch (error) {
      stopLiveAnalysis(false);
      uploadMessage.textContent = error instanceof Error ? error.message : "Upload failed safely";
    } finally {
      uploadButton.disabled = false;
      if (window.turnstile && !config.LOCAL_DEMO_MODE) window.turnstile.reset();
      turnstileToken = "";
    }
  });

  checkHealth();
  if (!config.LOCAL_DEMO_MODE && config.TURNSTILE_SITE_KEY) {
    const script = document.createElement("script");
    script.src = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";
    script.async = true;
    script.defer = true;
    script.addEventListener("load", mountTurnstile, { once: true });
    document.head.append(script);
  }
})();
