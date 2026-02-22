const state = {
  token: localStorage.getItem("medsetu_token") || "",
  role: localStorage.getItem("medsetu_role") || "",
  me: null,
  medicines: [],
  selectedPatient: null,
  selectedPrescription: null,
};

const $ = (id) => document.getElementById(id);

const authSection = $("authSection");
const doctorDashboard = $("doctorDashboard");
const pharmacistDashboard = $("pharmacistDashboard");
const patientDashboard = $("patientDashboard");
const sessionUser = $("sessionUser");
const logoutBtn = $("logoutBtn");

function api(path, opts = {}) {
  const headers = opts.headers || {};
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  if (!(opts.body instanceof FormData)) headers["Content-Type"] = "application/json";
  return fetch(path, { ...opts, headers }).then(async (res) => {
    const json = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(json.error || "Request failed");
    return json;
  });
}

function setMessage(id, text, error = false) {
  const el = $(id);
  if (!el) return;
  el.textContent = text || "";
  el.style.color = error ? "#b4302f" : "#0e3a8a";
}

function switchAuthTab(tab) {
  document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
  document.querySelector(`.tab[data-tab='${tab}']`).classList.add("active");
  $("loginFormWrap").classList.toggle("hidden", tab !== "login");
  $("registerFormWrap").classList.toggle("hidden", tab !== "register");
}

document.querySelectorAll(".tab").forEach((btn) => {
  btn.addEventListener("click", () => switchAuthTab(btn.dataset.tab));
});

function updateLoginRoleFields() {
  const role = $("loginRole").value;
  $("doctorLoginField").classList.toggle("hidden", role !== "doctor");
  $("pharmacistLoginField").classList.toggle("hidden", role !== "pharmacist");
}

function updateRegisterRoleFields() {
  const role = $("registerRole").value;
  $("patientRegFields").classList.toggle("hidden", role !== "patient");
  $("doctorRegFields").classList.toggle("hidden", role !== "doctor");
  $("pharmacistRegFields").classList.toggle("hidden", role !== "pharmacist");
}

$("loginRole").addEventListener("change", updateLoginRoleFields);
$("registerRole").addEventListener("change", updateRegisterRoleFields);

$("registerForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const role = $("registerRole").value;
  const payload = {
    role,
    full_name: $("regName").value.trim(),
    email: $("regEmail").value.trim(),
    password: $("regPassword").value,
  };

  if (role === "patient") {
    payload.mobile = $("regMobile").value.trim();
    payload.dob = $("regDob").value;
    payload.gender = $("regGender").value;
    payload.allergies = $("regAllergies").value.split(",").map((s) => s.trim()).filter(Boolean);
    payload.chronic_conditions = $("regChronic").value.split(",").map((s) => s.trim()).filter(Boolean);
  }

  if (role === "doctor") {
    payload.medical_registration_number = $("regMedicalReg").value.trim();
    payload.specialization = $("regSpecialization").value.trim();
  }

  if (role === "pharmacist") {
    payload.license_number = $("regLicense").value.trim();
    payload.pharmacy_name = $("regPharmacyName").value.trim();
  }

  try {
    const res = await api("/api/register", { method: "POST", body: JSON.stringify(payload) });
    state.token = res.token;
    state.role = res.role;
    localStorage.setItem("medsetu_token", state.token);
    localStorage.setItem("medsetu_role", state.role);
    setMessage("authMessage", "Registration successful.");
    await bootstrap();
  } catch (err) {
    setMessage("authMessage", err.message, true);
  }
});

$("loginForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const role = $("loginRole").value;
  const payload = {
    email: $("loginEmail").value.trim(),
    password: $("loginPassword").value,
  };

  if (role === "doctor") payload.medical_registration_number = $("loginMedicalReg").value.trim();
  if (role === "pharmacist") payload.license_number = $("loginLicense").value.trim();

  try {
    const res = await api("/api/login", { method: "POST", body: JSON.stringify(payload) });
    state.token = res.token;
    state.role = res.role;
    localStorage.setItem("medsetu_token", state.token);
    localStorage.setItem("medsetu_role", state.role);
    setMessage("authMessage", "Login successful.");
    await bootstrap();
  } catch (err) {
    setMessage("authMessage", err.message, true);
  }
});

logoutBtn.addEventListener("click", async () => {
  try {
    if (state.token) await api("/api/logout", { method: "POST" });
  } catch (_) {}

  localStorage.removeItem("medsetu_token");
  localStorage.removeItem("medsetu_role");
  state.token = "";
  state.role = "";
  state.me = null;

  authSection.classList.remove("hidden");
  doctorDashboard.classList.add("hidden");
  pharmacistDashboard.classList.add("hidden");
  patientDashboard.classList.add("hidden");
  logoutBtn.classList.add("hidden");
  sessionUser.textContent = "";
});

async function loadMedicines() {
  const res = await api("/api/medicines");
  state.medicines = res.medicines;
}

function resetDashboards() {
  doctorDashboard.classList.add("hidden");
  pharmacistDashboard.classList.add("hidden");
  patientDashboard.classList.add("hidden");
}

async function bootstrap() {
  if (!state.token) return;
  try {
    const me = await api("/api/me");
    state.me = me;
    state.role = me.user.role;
    localStorage.setItem("medsetu_role", state.role);
    await loadMedicines();

    authSection.classList.add("hidden");
    resetDashboards();
    logoutBtn.classList.remove("hidden");
    sessionUser.textContent = `${me.user.email} (${me.user.role})`;

    if (me.user.role === "doctor") {
      doctorDashboard.classList.remove("hidden");
      initDoctorUI();
    } else if (me.user.role === "pharmacist") {
      pharmacistDashboard.classList.remove("hidden");
      initPharmacistUI();
    } else {
      patientDashboard.classList.remove("hidden");
      await renderPatientDashboard();
      initPatientUI();
    }
  } catch (_) {
    localStorage.removeItem("medsetu_token");
    localStorage.removeItem("medsetu_role");
    state.token = "";
    state.role = "";
  }
}

function medOptionsHtml() {
  return state.medicines
    .map((m) => `<option value="${m.id}">${m.brand_name} (${m.generic_name})</option>`)
    .join("");
}

function addMedicineRow() {
  const wrapper = document.createElement("div");
  wrapper.className = "med-row";
  wrapper.innerHTML = `
    <label>Brand Medicine
      <select class="med-id">
        <option value="">Select medicine</option>
        ${medOptionsHtml()}
      </select>
    </label>
    <label>Generic Name
      <input class="generic" type="text" readonly />
    </label>
    <label>Dosage (editable)
      <input class="dosage" type="text" />
    </label>
    <label>Indications
      <input class="indications" type="text" readonly />
    </label>
    <label class="full">Precautions
      <input class="precautions" type="text" readonly />
    </label>
    <button class="btn-secondary remove-med" type="button">Remove</button>
  `;

  const medSelect = wrapper.querySelector(".med-id");
  medSelect.addEventListener("change", () => {
    const m = state.medicines.find((x) => String(x.id) === medSelect.value);
    wrapper.querySelector(".generic").value = m ? m.generic_name : "";
    wrapper.querySelector(".dosage").value = m ? m.standard_dosage : "";
    wrapper.querySelector(".indications").value = m ? m.indications : "";
    wrapper.querySelector(".precautions").value = m ? m.precautions : "";
  });

  wrapper.querySelector(".remove-med").addEventListener("click", () => wrapper.remove());
  $("medRows").appendChild(wrapper);
}

function statusClass(status) {
  if (status === "Active") return "status-pill status-active";
  if (status === "Dispensed") return "status-pill status-dispensed";
  return "status-pill status-expired";
}

function initDoctorUI() {
  if (!$("medRows").children.length) addMedicineRow();

  $("addMedRowBtn").onclick = () => addMedicineRow();

  $("searchPatientBtn").onclick = async () => {
    setMessage("otpMsg", "");
    state.selectedPatient = null;
    $("patientOverview").innerHTML = "";
    $("otpFlowBox").classList.add("hidden");
    const mobile = $("doctorPatientMobile").value.trim();
    if (!mobile) return;

    try {
      const res = await api(`/api/doctor/patients/search?mobile=${encodeURIComponent(mobile)}`);
      state.selectedPatient = res.patient;
      $("doctorPatientResult").innerHTML = `<p><strong>${res.patient.full_name}</strong> (${res.patient.mobile})</p>`;
      $("otpFlowBox").classList.remove("hidden");
    } catch (err) {
      $("doctorPatientResult").innerHTML = `<p style='color:#b4302f;'>${err.message}</p>`;
    }
  };

  $("sendOtpBtn").onclick = async () => {
    if (!state.selectedPatient) return;
    try {
      const res = await api("/api/doctor/access/send-otp", {
        method: "POST",
        body: JSON.stringify({ patient_id: state.selectedPatient.id }),
      });
      $("otpDisplay").textContent = `Simulated OTP: ${res.otp} (Expires: ${new Date(res.expires_at).toLocaleString()})`;
    } catch (err) {
      setMessage("otpMsg", err.message, true);
    }
  };

  $("verifyOtpBtn").onclick = async () => {
    if (!state.selectedPatient) return;
    const otp_code = $("otpInput").value.trim();
    try {
      const res = await api("/api/doctor/access/verify-otp", {
        method: "POST",
        body: JSON.stringify({ patient_id: state.selectedPatient.id, otp_code }),
      });
      setMessage("otpMsg", `Access granted till ${new Date(res.access_expires_at).toLocaleString()}`);
      await loadDoctorPatientOverview();
    } catch (err) {
      setMessage("otpMsg", err.message, true);
    }
  };

  $("createPrescriptionBtn").onclick = async () => {
    if (!state.selectedPatient) return setMessage("prescMsg", "Select patient and verify OTP first", true);

    const meds = [...document.querySelectorAll(".med-row")]
      .map((row) => ({
        medicine_id: Number(row.querySelector(".med-id").value),
        dosage: row.querySelector(".dosage").value.trim(),
      }))
      .filter((m) => m.medicine_id);

    if (!meds.length) return setMessage("prescMsg", "Add at least one medicine", true);

    try {
      const res = await api("/api/doctor/prescriptions", {
        method: "POST",
        body: JSON.stringify({
          patient_id: state.selectedPatient.id,
          medicines: meds,
          doctor_notes: $("doctorNotes").value,
          digital_signature: $("digitalSignature").value,
        }),
      });

      setMessage("prescMsg", "Prescription created successfully");
      $("createdPrescriptionCard").classList.remove("hidden");
      $("createdPrescriptionId").textContent = `Prescription ID: ${res.prescription_id}`;
      const qrContainer = $("qrContainer");
      qrContainer.innerHTML = "";
      new QRCode(qrContainer, {
        text: res.qr_payload,
        width: 120,
        height: 120,
      });
      await loadDoctorPatientOverview();
    } catch (err) {
      setMessage("prescMsg", err.message, true);
    }
  };

  $("uploadReportBtn").onclick = async () => {
    if (!state.selectedPatient) return setMessage("reportUploadMsg", "Select patient first", true);
    const file = $("doctorReportFile").files[0];
    if (!file) return setMessage("reportUploadMsg", "Choose a file", true);

    const form = new FormData();
    form.append("file", file);

    try {
      await api(`/api/doctor/patient/${state.selectedPatient.id}/reports`, {
        method: "POST",
        body: form,
      });
      setMessage("reportUploadMsg", "Report uploaded.");
      await loadDoctorPatientOverview();
    } catch (err) {
      setMessage("reportUploadMsg", err.message, true);
    }
  };
}

async function loadDoctorPatientOverview() {
  if (!state.selectedPatient) return;
  try {
    const res = await api(`/api/doctor/patient/${state.selectedPatient.id}/overview`);
    const p = res.profile;
    const prescHtml = res.prescriptions.length
      ? res.prescriptions
          .map(
            (x) => `<li>${x.prescription_id} - <span class="${statusClass(x.status)}">${x.status}</span> (${new Date(x.created_at).toLocaleString()})</li>`
          )
          .join("")
      : "<li>No prescriptions yet</li>";

    const reportHtml = res.reports.length
      ? res.reports.map((r) => `<li><a href="/api/files/reports/${r.id}" target="_blank">${r.file_name}</a></li>`).join("")
      : "<li>No reports uploaded</li>";

    $("patientOverview").innerHTML = `
      <p><strong>${p.full_name}</strong> (${p.mobile})</p>
      <p>Allergies: ${(p.allergies || []).join(", ") || "None"}</p>
      <p>Chronic Conditions: ${(p.chronic_conditions || []).join(", ") || "None"}</p>
      <h4>Past Prescriptions</h4>
      <ul class="clean">${prescHtml}</ul>
      <h4>Reports</h4>
      <ul class="clean">${reportHtml}</ul>
    `;
  } catch (err) {
    $("patientOverview").innerHTML = `<p style='color:#b4302f;'>${err.message}</p>`;
  }
}

function initPharmacistUI() {
  $("lookupPrescriptionBtn").onclick = async () => {
    const value = $("lookupValue").value.trim();
    if (!value) return;

    try {
      const res = await api("/api/pharmacist/prescriptions/lookup", {
        method: "POST",
        body: JSON.stringify({ value }),
      });
      const p = res.prescription;
      state.selectedPrescription = p;

      const meds = p.medicines.map((m) => `<li>${m.brand_name} (${m.generic_name}) - ${m.dosage}</li>`).join("");
      $("lookupResult").innerHTML = `
        <p><strong>${p.prescription_id}</strong> <span class="${statusClass(p.status)}">${p.status}</span></p>
        <p>Doctor: ${p.doctor_name} (${p.doctor_reg})</p>
        <p>Patient: ${p.patient_name} (${p.patient_mobile})</p>
        <ul class="clean">${meds}</ul>
        <p>Notes: ${p.doctor_notes || "-"}</p>
        <button id="dispenseBtn" class="btn-primary" ${p.status !== "Active" ? "disabled" : ""}>Mark as Dispensed</button>
      `;

      const dispenseBtn = $("dispenseBtn");
      if (dispenseBtn) {
        dispenseBtn.onclick = async () => {
          try {
            const dRes = await api(`/api/pharmacist/prescriptions/${p.prescription_id}/dispense`, { method: "POST" });
            $("lookupResult").insertAdjacentHTML("beforeend", `<p>${dRes.message}</p>`);
            dispenseBtn.disabled = true;
            await $("lookupPrescriptionBtn").onclick();
          } catch (err) {
            $("lookupResult").insertAdjacentHTML("beforeend", `<p style='color:#b4302f;'>${err.message}</p>`);
          }
        };
      }
    } catch (err) {
      $("lookupResult").innerHTML = `<p style='color:#b4302f;'>${err.message}</p>`;
    }
  };
}

async function renderPatientDashboard() {
  try {
    const [history, logs] = await Promise.all([api("/api/patient/history"), api("/api/patient/access-logs")]);
    const p = history.patient;

    $("patientProfile").innerHTML = `
      <p><strong>${p.full_name}</strong></p>
      <p>Mobile: ${p.mobile}</p>
      <p>Allergies: ${(p.allergies || []).join(", ") || "None"}</p>
      <p>Chronic: ${(p.chronic_conditions || []).join(", ") || "None"}</p>
    `;

    const prescHtml = history.prescriptions.length
      ? history.prescriptions
          .map((x) => {
            const meds = x.medicines.map((m) => `${m.brand_name} (${m.dosage})`).join(", ");
            return `
            <div class="card">
              <p><strong>${x.prescription_id}</strong> <span class="${statusClass(x.status)}">${x.status}</span></p>
              <p>Doctor: ${x.doctor_name}</p>
              <p>Medicines: ${meds}</p>
              <p>Notes: ${x.doctor_notes || "-"}</p>
              <p>Signature: ${x.digital_signature || "-"}</p>
              <button class="btn-secondary pdf-btn" data-id="${x.prescription_id}">Download PDF</button>
            </div>`;
          })
          .join("")
      : "<p>No prescriptions found.</p>";

    $("patientPrescriptions").innerHTML = prescHtml;

    document.querySelectorAll(".pdf-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const id = btn.dataset.id;
        const rx = history.prescriptions.find((x) => x.prescription_id === id);
        if (rx) generatePrescriptionPdf(rx, p);
      });
    });

    const timelineHtml = history.timeline.length
      ? history.timeline
          .map(
            (t) => `
            <div class="timeline-item">
              <p><strong>${t.title}</strong> <span class="${statusClass(t.status)}">${t.status}</span></p>
              <small>${new Date(t.timestamp).toLocaleString()}</small>
            </div>
          `
          )
          .join("")
      : "<p>No timeline events.</p>";

    $("timelineView").innerHTML = timelineHtml;

    const logsHtml = logs.logs.length
      ? logs.logs
          .map(
            (l) => `
            <div class="timeline-item">
              <p><strong>${l.action}</strong> ${l.success ? "" : "(Failed)"}</p>
              <p>${l.doctor_name || l.pharmacist_name || "System"} | ${l.details || "-"}</p>
              <small>${new Date(l.created_at).toLocaleString()}</small>
            </div>`
          )
          .join("")
      : "<p>No access logs.</p>";

    $("accessLogs").innerHTML = logsHtml;
  } catch (err) {
    $("patientProfile").innerHTML = `<p style='color:#b4302f;'>${err.message}</p>`;
  }
}

function generatePrescriptionPdf(rx, patient) {
  const { jsPDF } = window.jspdf;
  const doc = new jsPDF();
  let y = 15;

  doc.setFontSize(16);
  doc.text("MedSetu e-Prescription", 14, y);
  y += 10;

  doc.setFontSize(11);
  doc.text(`Prescription ID: ${rx.prescription_id}`, 14, y); y += 7;
  doc.text(`Patient: ${patient.full_name} (${patient.mobile})`, 14, y); y += 7;
  doc.text(`Doctor: ${rx.doctor_name}`, 14, y); y += 7;
  doc.text(`Created At: ${new Date(rx.created_at).toLocaleString()}`, 14, y); y += 8;

  doc.text("Medicines:", 14, y); y += 7;
  rx.medicines.forEach((m) => {
    doc.text(`- ${m.brand_name} (${m.generic_name}) | ${m.dosage}`, 14, y);
    y += 6;
  });
  y += 2;
  doc.text(`Notes: ${rx.doctor_notes || "-"}`, 14, y); y += 7;
  doc.text(`Status: ${rx.status}`, 14, y); y += 7;
  doc.text(`Digital Signature: ${rx.digital_signature || "-"}`, 14, y);

  doc.save(`${rx.prescription_id}.pdf`);
}

function initPatientUI() {
  $("uploadExternalBtn").onclick = async () => {
    const file = $("externalPrescFile").files[0];
    if (!file) return setMessage("externalUploadMsg", "Choose a file", true);

    const form = new FormData();
    form.append("file", file);

    try {
      await api("/api/patient/external-prescriptions", {
        method: "POST",
        body: form,
      });
      setMessage("externalUploadMsg", "External prescription uploaded.");
      await renderPatientDashboard();
    } catch (err) {
      setMessage("externalUploadMsg", err.message, true);
    }
  };
}

updateLoginRoleFields();
updateRegisterRoleFields();
bootstrap();
