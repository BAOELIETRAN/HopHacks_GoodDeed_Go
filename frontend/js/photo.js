/* Photo capture, shared by every screen that accepts an image.

   Every photo box in the app gets the same two choices, always visible:
     - Take a photo    (the device camera, with our own preview / retake / confirm)
     - Upload a photo  (the device's files or photo library)

   Written once because there are four upload spots (quest proof, community
   report, report after-photo, campaign proof) and they must not drift apart.

   Nothing here touches `document` or `window` at import time, so the pure
   helpers at the top can be unit-tested in plain Node. */

import { ico } from "./icons.js";

export const MAX_CAPTURE_EDGE = 1600;

/* ---------------------------------------------------------------- pure helpers */

/** Scale (width, height) down so the long edge is at most `max`. Never scales up. */
export function fitWithin(width, height, max = MAX_CAPTURE_EDGE) {
  const longest = Math.max(width, height);
  if (!(longest > max)) return { width, height };
  const scale = max / longest;
  return { width: Math.round(width * scale), height: Math.round(height * scale) };
}

/** Which camera paths this device offers.
 *  `inApp`  - getUserMedia exists, so we can show our own live preview. It is
 *             absent on plain-http pages (anything but https or localhost).
 *  `touch`  - a phone or tablet, where the OS camera app (`capture`) is a good
 *             fallback when `inApp` is missing or the user blocked access. */
export function cameraSupport(nav = globalThis.navigator, win = globalThis.window) {
  const inApp = typeof nav?.mediaDevices?.getUserMedia === "function";
  const hasTouch = (nav?.maxTouchPoints ?? 0) > 0 || (win && "ontouchstart" in win);
  const coarse =
    !win || typeof win.matchMedia !== "function" || win.matchMedia("(pointer: coarse)").matches;
  return { inApp, touch: Boolean(hasTouch && coarse) };
}

/** Turn a getUserMedia failure into words a person can act on.
 *  `retry` says whether trying again could plausibly work. */
export function describeCameraError(err) {
  const name = err?.name || "";
  if (name === "NotAllowedError" || name === "PermissionDeniedError" || name === "SecurityError") {
    return {
      retry: true,
      message:
        "Camera access is blocked. Allow the camera for this site in your browser settings, " +
        "then try again — or upload a photo instead.",
    };
  }
  if (name === "NotFoundError" || name === "DevicesNotFoundError" || name === "OverconstrainedError") {
    return {
      retry: false,
      message: "We couldn't find a camera on this device. You can upload a photo instead.",
    };
  }
  if (name === "NotReadableError" || name === "TrackStartError" || name === "AbortError") {
    return {
      retry: true,
      message:
        "The camera is busy — another app may be using it. Close that app and try again, " +
        "or upload a photo instead.",
    };
  }
  return { retry: true, message: "The camera couldn't start. You can try again or upload a photo instead." };
}

/** Read a File into a data: URL. The backend stores photo_url as a string and
 *  the AI agent accepts data URLs, so the demo needs no file storage. */
export function fileToDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(new Error("Could not read that image"));
    reader.readAsDataURL(file);
  });
}

/** Shrink a photo before upload. Phone cameras produce 3-6MB JPEGs; sending
 *  those as base64 JSON is slow and can exceed request limits. */
export async function compressImage(file, maxEdge = 1024, quality = 0.82) {
  const dataUrl = await fileToDataUrl(file);
  try {
    const img = await new Promise((resolve, reject) => {
      const i = new Image();
      i.onload = () => resolve(i);
      i.onerror = () => reject(new Error("bad image"));
      i.src = dataUrl;
    });
    const scale = Math.min(1, maxEdge / Math.max(img.width, img.height));
    if (scale === 1 && dataUrl.length < 900_000) return dataUrl;
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(img.width * scale);
    canvas.height = Math.round(img.height * scale);
    canvas.getContext("2d").drawImage(img, 0, 0, canvas.width, canvas.height);
    return canvas.toDataURL("image/jpeg", quality);
  } catch {
    return dataUrl; // HEIC or similar the canvas can't decode -- send as-is
  }
}

/* --------------------------------------------------------------- camera dialog */

const CAMERA_TEMPLATE = `
  <div class="cam-top">
    <button type="button" class="cam-close" data-cam-cancel aria-label="Close camera">${ico("close", { size: 20 })}</button>
    <strong>Take a photo</strong>
    <span></span>
  </div>
  <div class="cam-stage">
    <video class="cam-video" data-cam-video autoplay playsinline muted></video>
    <img class="cam-still" data-cam-still alt="Your photo" hidden>
    <p class="cam-status" data-cam-status role="status" aria-live="polite"></p>
    <div class="cam-error" data-cam-error hidden>
      <p data-cam-error-text role="alert"></p>
      <div class="cam-error-actions">
        <button type="button" class="btn btn-primary" data-cam-retry>Try again</button>
        <button type="button" class="btn btn-ghost" data-cam-upload>Upload a photo</button>
        <button type="button" class="btn btn-ghost" data-cam-native hidden>Use your phone's camera app</button>
      </div>
    </div>
  </div>
  <div class="cam-controls" data-cam-live>
    <button type="button" class="cam-flip" data-cam-flip aria-label="Switch camera" hidden>${ico("flip", { size: 22 })}</button>
    <button type="button" class="cam-shutter" data-cam-shoot aria-label="Take photo" disabled></button>
    <span class="cam-spacer"></span>
  </div>
  <div class="cam-controls cam-review" data-cam-review hidden>
    <button type="button" class="btn btn-ghost" data-cam-retake>Retake</button>
    <button type="button" class="btn btn-primary" data-cam-use>Use photo</button>
  </div>`;

/** Open the in-app camera: live preview -> capture -> review (retake / use).
 *
 *  Asks for the rear camera (`facingMode: ideal environment`); laptops and
 *  phones without one simply get whatever camera they have. The stream is
 *  stopped on every way out -- close, Escape, use, navigation -- because a
 *  camera light left on after the dialog is gone reads as spying.
 *
 *  `onCapture(File)` fires only when the user confirms with "Use photo". */
export function openCameraDialog({ container, onCapture, onUpload, onNativeCamera }) {
  const doc = container.ownerDocument;
  const win = doc.defaultView;
  const opener = doc.activeElement;

  const overlay = doc.createElement("div");
  overlay.className = "cam-overlay";
  overlay.setAttribute("role", "dialog");
  overlay.setAttribute("aria-modal", "true");
  overlay.setAttribute("aria-label", "Take a photo");
  overlay.innerHTML = CAMERA_TEMPLATE;
  const $ = (selector) => overlay.querySelector(selector);

  const video = $("[data-cam-video]");
  const still = $("[data-cam-still]");
  const status = $("[data-cam-status]");
  const errorBox = $("[data-cam-error]");
  const live = $("[data-cam-live]");
  const review = $("[data-cam-review]");
  const shoot = $("[data-cam-shoot]");
  const flip = $("[data-cam-flip]");
  const nativeBtn = $("[data-cam-native]");
  const retryBtn = $("[data-cam-retry]");
  nativeBtn.hidden = !onNativeCamera;

  let stream = null;
  let facing = "environment";
  let blob = null;
  let stillUrl = null;
  let closed = false;

  const stopStream = () => {
    stream?.getTracks().forEach((t) => t.stop());
    stream = null;
    video.srcObject = null;
  };
  const revokeStill = () => {
    if (stillUrl) URL.revokeObjectURL(stillUrl);
    stillUrl = null;
  };
  const setState = (next) => {
    video.hidden = next !== "live";
    still.hidden = next !== "review";
    live.hidden = next !== "live";
    review.hidden = next !== "review";
    errorBox.hidden = next !== "error";
    status.hidden = next !== "live";
  };

  function close(restoreFocus = true) {
    if (closed) return;
    closed = true;
    stopStream();
    revokeStill();
    win.removeEventListener("hashchange", onLeave);
    win.removeEventListener("pagehide", onLeave);
    overlay.remove();
    if (restoreFocus) opener?.focus?.();
  }
  const onLeave = () => close(false);

  function showError(err) {
    stopStream();
    const info = describeCameraError(err);
    $("[data-cam-error-text]").textContent = info.message;
    retryBtn.hidden = !info.retry;
    setState("error");
    (info.retry ? retryBtn : $("[data-cam-upload]")).focus();
  }

  async function updateFlip() {
    try {
      const devices = await doc.defaultView.navigator.mediaDevices.enumerateDevices();
      flip.hidden = devices.filter((d) => d.kind === "videoinput").length < 2;
    } catch {
      flip.hidden = true;
    }
  }

  async function start() {
    stopStream();
    setState("live");
    shoot.disabled = true;
    status.textContent = "Starting camera…";

    let s;
    try {
      s = await win.navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: facing }, width: { ideal: 1920 }, height: { ideal: 1080 } },
        audio: false,
      });
    } catch (err) {
      if (!closed) showError(err);
      return;
    }
    // Closed while the permission prompt was still up: don't leave it running.
    if (closed) {
      s.getTracks().forEach((t) => t.stop());
      return;
    }

    stream = s;
    video.srcObject = s;
    try {
      await video.play();
    } catch {
      /* the autoplay attribute covers browsers that reject play() here */
    }

    const track = s.getVideoTracks()[0];
    const actual = track?.getSettings?.().facingMode;
    if (actual) facing = actual;
    video.classList.toggle("cam-mirror", actual === "user"); // mirror the selfie preview only
    // Unplugged, or permission revoked mid-session.
    track?.addEventListener("ended", () => {
      if (!closed && !live.hidden) showError({ name: "NotReadableError" });
    });

    status.textContent = "";
    shoot.disabled = false;
    if (doc.activeElement === doc.body || overlay.contains(doc.activeElement)) shoot.focus();
    updateFlip();
  }

  function capture() {
    if (!stream || !video.videoWidth) return;
    const { width, height } = fitWithin(video.videoWidth, video.videoHeight);
    const canvas = doc.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    canvas.getContext("2d").drawImage(video, 0, 0, width, height);
    canvas.toBlob(
      (result) => {
        if (closed) return;
        if (!result) return showError({ name: "UnknownError" });
        blob = result;
        revokeStill();
        stillUrl = URL.createObjectURL(result);
        still.src = stillUrl;
        video.pause();
        setState("review");
        $("[data-cam-use]").focus();
      },
      "image/jpeg",
      0.9,
    );
  }

  function retake() {
    revokeStill();
    blob = null;
    const track = stream?.getVideoTracks()[0];
    if (!stream || track?.readyState === "ended") return start();
    setState("live");
    video.play().catch(() => {});
    shoot.focus();
  }

  function use() {
    if (!blob) return;
    const file = new File([blob], "camera-photo.jpg", { type: "image/jpeg", lastModified: Date.now() });
    close();
    onCapture(file);
  }

  $("[data-cam-cancel]").onclick = () => close();
  shoot.onclick = capture;
  $("[data-cam-retake]").onclick = retake;
  $("[data-cam-use]").onclick = use;
  retryBtn.onclick = start;
  flip.onclick = () => {
    facing = facing === "environment" ? "user" : "environment";
    start();
  };
  // These hand control to another picker, which must be opened from this same
  // click for the browser to allow it -- so close first, then call it.
  $("[data-cam-upload]").onclick = () => {
    close(false);
    onUpload();
  };
  nativeBtn.onclick = () => {
    close(false);
    onNativeCamera?.();
  };

  overlay.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      e.stopPropagation();
      close();
      return;
    }
    if (e.key !== "Tab") return;
    const items = [...overlay.querySelectorAll("button:not([disabled])")].filter((el) => el.offsetParent !== null);
    if (!items.length) return;
    const first = items[0];
    const last = items[items.length - 1];
    if (e.shiftKey && doc.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && doc.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  });

  // Leaving the screen (back button, nav) must not strand a running camera.
  win.addEventListener("hashchange", onLeave);
  win.addEventListener("pagehide", onLeave);

  container.appendChild(overlay);
  $("[data-cam-cancel]").focus();
  start();

  return { close };
}

/* ------------------------------------------------------------------ the widget */

/** Wire up a photo box: two visible choices -> preview -> report problems.
 *
 *  `dropzone` is the existing <label class="dropzone"> that holds the hidden
 *  file <input> and the placeholder `guide`. The two buttons are added just
 *  below it, so the four screens need no markup changes to gain them.
 *
 *  Guarantees (kept from the version this replaced):
 *   - the placeholder is only hidden once the image has actually decoded
 *   - a decode failure restores the placeholder and reports a real reason
 *   - object URLs are revoked when replaced, so picking ten photos doesn't
 *     leak ten blobs
 *
 *  Calls `onPhoto(dataUrl)` when a photo is set (upload, or camera + "Use
 *  photo"), `onPhoto(null)` when it is removed or unreadable, and
 *  `onError(message | null)` for anything worth telling the user. */
export function setupPhotoInput({ dropzone, input, guide, onPhoto, onError }) {
  const doc = dropzone.ownerDocument;
  const support = cameraSupport();
  let objectUrl = null;
  let hasPhoto = false;

  // The plain picker: no `capture`, or phones would skip the photo library.
  input.removeAttribute("capture");

  // Fallback for phones when the in-app camera isn't available. It lives
  // outside the <label> so tapping the dropzone can never activate it.
  const nativeCamera = input.cloneNode();
  nativeCamera.id = `${input.id || "photo"}-camera`;
  nativeCamera.setAttribute("capture", "environment");
  nativeCamera.hidden = true;
  nativeCamera.setAttribute("aria-hidden", "true");
  nativeCamera.tabIndex = -1;

  const actions = doc.createElement("div");
  actions.className = "photo-actions";
  actions.innerHTML = `
    <div class="btn-row" role="group" aria-label="Add a photo">
      <button type="button" class="btn btn-ghost photo-btn" data-photo-camera>
        ${ico("camera", { size: 18 })}<span data-photo-camera-label>Take a photo</span>
      </button>
      <button type="button" class="btn btn-ghost photo-btn" data-photo-upload>
        ${ico("image", { size: 18 })}<span data-photo-upload-label>Upload a photo</span>
      </button>
    </div>
    <button type="button" class="btn-link photo-remove" data-photo-remove hidden>Remove photo</button>`;
  actions.appendChild(nativeCamera);
  dropzone.insertAdjacentElement("afterend", actions);

  const cameraBtn = actions.querySelector("[data-photo-camera]");
  const uploadBtn = actions.querySelector("[data-photo-upload]");
  const removeBtn = actions.querySelector("[data-photo-remove]");

  const setHasPhoto = (value) => {
    hasPhoto = value;
    dropzone.classList.toggle("has-photo", value);
    actions.querySelector("[data-photo-camera-label]").textContent = value ? "Retake photo" : "Take a photo";
    actions.querySelector("[data-photo-upload-label]").textContent = value ? "Choose another" : "Upload a photo";
    removeBtn.hidden = !value;
  };

  const release = () => {
    if (objectUrl) {
      URL.revokeObjectURL(objectUrl);
      objectUrl = null;
    }
  };

  const showPlaceholder = () => {
    dropzone.querySelector("img")?.remove();
    if (guide) guide.style.display = "";
    release();
    setHasPhoto(false);
  };

  const fail = (message) => {
    console.warn("[gdg] photo:", message);
    showPlaceholder();
    onPhoto?.(null);
    onError?.(message);
  };

  // Uploads and camera captures both arrive here as a File.
  const handle = async (file) => {
    if (!file) return;
    console.info("[gdg] photo selected:", file.name, file.type || "(no type)", `${Math.round(file.size / 1024)}KB`);
    onError?.(null);

    let dataUrl;
    try {
      dataUrl = await compressImage(file);
    } catch (err) {
      return fail(err?.message || "Couldn't read that image.");
    }

    // Preview from an object URL: cheaper than decoding a multi-megabyte
    // base64 string, and it reveals a format the browser cannot render
    // before the user waits on an upload that would fail.
    release();
    objectUrl = URL.createObjectURL(file);

    const img = new Image();
    img.alt = "Your photo";
    const show = (el) => {
      dropzone.querySelector("img")?.remove();
      dropzone.appendChild(el);
      if (guide) guide.style.display = "none";
      setHasPhoto(true);
      onPhoto?.(dataUrl);
    };
    img.onload = () => show(img);
    img.onerror = () => {
      // The compressed copy can still be fine when the original is a
      // format the browser will not preview.
      const fallback = new Image();
      fallback.alt = "Your photo";
      fallback.onload = () => show(fallback);
      fallback.onerror = () =>
        fail(
          "This device saved that photo in a format browsers can't show (usually HEIC). " +
            "On iPhone: Settings › Camera › Formats › Most Compatible, then retake.",
        );
      fallback.src = dataUrl;
    };
    img.src = objectUrl;
  };

  input.onchange = () => handle(input.files?.[0]);
  nativeCamera.onchange = () => handle(nativeCamera.files?.[0]);

  const openPicker = () => {
    onError?.(null);
    input.click();
  };

  const openCamera = () => {
    onError?.(null);
    if (!support.inApp) {
      // No live-preview camera (typically a plain-http page). A phone can still
      // hand off to its camera app; anything else needs a clear explanation.
      if (support.touch) return nativeCamera.click();
      return onError?.(
        "This browser can't open the camera here — it needs a secure (https) connection. " +
          "You can upload a photo instead.",
      );
    }
    openCameraDialog({
      container: doc.getElementById("app") || doc.body,
      onCapture: handle,
      onUpload: openPicker,
      onNativeCamera: support.touch ? () => nativeCamera.click() : null,
    });
  };

  cameraBtn.onclick = openCamera;
  uploadBtn.onclick = openPicker;
  removeBtn.onclick = () => {
    showPlaceholder();
    onPhoto?.(null);
    onError?.(null);
  };

  return { reset: showPlaceholder, release, openCamera, openPicker, hasPhoto: () => hasPhoto };
}
