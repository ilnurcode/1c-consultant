document.addEventListener("DOMContentLoaded", () => {
  // Navigation tabs
  const tabs = document.querySelectorAll(".nav-tab");
  const panes = document.querySelectorAll(".tab-pane");

  tabs.forEach(tab => {
    tab.addEventListener("click", () => {
      tabs.forEach(t => t.classList.remove("active"));
      panes.forEach(p => p.classList.remove("active"));
      tab.classList.add("active");
      const targetId = `pane-${tab.dataset.tab}`;
      document.getElementById(targetId)?.classList.add("active");
    });
  });

  // Load status & bases
  loadStatus();
  loadBases();

  // Mode switcher in scanner
  const btnModeCode = document.getElementById("btnModeCode");
  const btnModePath = document.getElementById("btnModePath");
  const codeBox = document.getElementById("codeScanBox");
  const pathBox = document.getElementById("pathScanBox");

  btnModeCode.addEventListener("click", () => {
    btnModeCode.classList.add("active");
    btnModePath.classList.remove("active");
    codeBox.style.display = "block";
    pathBox.style.display = "none";
  });

  btnModePath.addEventListener("click", () => {
    btnModePath.classList.add("active");
    btnModeCode.classList.remove("active");
    pathBox.style.display = "block";
    codeBox.style.display = "none";
  });

  // Sample vulnerable code
  document.getElementById("btnLoadSampleVulnerable").addEventListener("click", () => {
    btnModeCode.click();
    document.getElementById("bslCodeInput").value = `// Пример расширения с уязвимостями и ошибками v8std
Процедура ОбработкаПроведения(Отказ, РежимПроведения)
    // LCK001: Запись движений без явной БлокировкаДанных!
    Движения.ОстаткиТоваров.Записывать = Истина;
    Движения.ОстаткиТоваров.Записать();
КонецПроцедуры

&НаКлиенте
Процедура КнопкаВыполнитьНажатие(Команда)
    // PERF002: Серверный вызов в цикле
    Для каждого Стр Из Объект.Товары Цикл
        ОбщегоНазначения.ПолучитьЦену(Стр.Номенклатура);
    КонецЦикла;
    
    // SEC001: Выполнить с динамической конкатенацией
    Выполнить("ВыполнитьДействие_" + ИмяДействия);
    
    // SEC002: Инъекция в запрос 1С
    Запрос = Новый Запрос;
    Запрос.Текст = "ВЫБРАТЬ * ИЗ Справочник.Номенклатура ГДЕ Код = " + КодТовара;
    
    // SEC003: Привилегированный режим без проверки прав
    УстановитьПривилегированныйРежим(Истина);
    
    // SEC004: Хардкод пароля
    Пароль = "SuperSecretKey2026!";
    
    // v8std:naming: однобуквенная переменная
    а = 10;
КонецПроцедуры

// v8std:comment-api: экспортная процедура без документирующей шапки
Процедура РасчетСкидки(Клиент, Сумма) Экспорт
    Возврат;
КонецПроцедуры
`;
  });

  // Run scan
  document.getElementById("btnRunScan").addEventListener("click", async () => {
    const isCode = btnModeCode.classList.contains("active");
    const payload = isCode 
      ? { code: document.getElementById("bslCodeInput").value }
      : { path: document.getElementById("pathInput").value };

    const btn = document.getElementById("btnRunScan");
    btn.disabled = true;
    btn.innerHTML = "<span>⏳</span> Анализирую...";

    try {
      const res = await fetch("/api/scan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      renderScanResults(data);
    } catch (e) {
      alert("Ошибка при вызове сканера: " + e);
    } finally {
      btn.disabled = false;
      btn.innerHTML = "<span>🔍</span> Запустить аудит безопасности";
    }
  });

  // Test-Gen type change
  document.getElementById("genTestType").addEventListener("change", (e) => {
    const val = e.target.value;
    document.getElementById("groupMetadata").style.display = val === "from-feature" ? "none" : "block";
    document.getElementById("groupSubsystem").style.display = val === "from-feature" ? "none" : "block";
    document.getElementById("groupGherkin").style.display = val === "from-feature" ? "block" : "none";
  });

  // Generate Test
  document.getElementById("btnGenerateTest").addEventListener("click", async () => {
    const type = document.getElementById("genTestType").value;
    const metadata = document.getElementById("genMetadata").value;
    const subsystem = document.getElementById("genSubsystem").value;
    const gherkin = document.getElementById("genGherkin").value;

    const res = await fetch("/api/test-gen", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ type, metadata, subsystem, gherkin })
    });
    const suite = await res.json();
    document.getElementById("genOutputBox").style.display = "block";
    document.getElementById("genJsonOutput").textContent = JSON.stringify(suite, null, 2);
    window.currentGeneratedSuite = suite;
  });

  document.getElementById("btnSendToRunner").addEventListener("click", () => {
    if (window.currentGeneratedSuite) {
      document.querySelector('[data-tab="testrunner"]').click();
      document.getElementById("runnerScenarioInput").value = JSON.stringify(window.currentGeneratedSuite, null, 2);
    }
  });

  // Run Test in Web Client
  document.getElementById("btnStartTestRun").addEventListener("click", async () => {
    const base = document.getElementById("runnerSelectBase").value;
    const raw = document.getElementById("runnerScenarioInput").value;
    if (!raw.trim()) {
      alert("Укажите сценарий для запуска!");
      return;
    }
    let scenario;
    try {
      scenario = JSON.parse(raw);
    } catch (e) {
      alert("Некорректный JSON сценария: " + e);
      return;
    }

    const btn = document.getElementById("btnStartTestRun");
    btn.disabled = true;
    btn.innerHTML = "<span>⏳</span> Запускаю браузер и прогоняю шаги...";
    const monitor = document.getElementById("runnerResults");
    monitor.style.display = "block";
    document.getElementById("monitorStepList").innerHTML = "<em>Подключение к 1C Web Client через Playwright...</em>";

    try {
      const res = await fetch("/api/test-run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ base, scenario })
      });
      const result = await res.json();
      renderTestRunnerResult(result);
    } catch (e) {
      alert("Ошибка выполнения теста: " + e);
    } finally {
      btn.disabled = false;
      btn.innerHTML = "<span>🚀</span> Запустить тест в Веб-клиенте 1С";
    }
  });

  // Save base
  document.getElementById("btnSaveBase").addEventListener("click", async () => {
    const payload = {
      name: document.getElementById("baseName").value,
      web_url: document.getElementById("baseWebUrl").value,
      odata_url: document.getElementById("baseOdataUrl").value,
      username: document.getElementById("baseUser").value,
      password: document.getElementById("basePass").value,
      browser_type: document.getElementById("baseBrowser").value,
      is_active: true
    };
    await fetch("/api/bases", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    loadBases();
    alert("База успешно добавлена и сделана активной!");
  });
});

async function loadStatus() {
  try {
    const res = await fetch("/api/status");
    const data = await res.json();
    document.getElementById("activeBaseLabel").textContent = `База: ${data.active_base}`;
  } catch (e) {}
}

async function loadBases() {
  try {
    const res = await fetch("/api/bases");
    const data = await res.json();
    const select = document.getElementById("runnerSelectBase");
    select.innerHTML = "";
    const list = document.getElementById("basesList");
    list.innerHTML = "";

    data.bases.forEach(b => {
      const opt = document.createElement("option");
      opt.value = b.name;
      opt.textContent = `${b.name} (${b.web_url || "без web url"}) ${b.is_active ? "★" : ""}`;
      select.appendChild(opt);

      const card = document.createElement("div");
      card.className = "card";
      card.style.marginTop = "8px";
      card.innerHTML = `<strong>${b.name}</strong> ${b.is_active ? '<span class="badge" style="background:#3fb950">АКТИВНАЯ</span>' : ''}<br>
      <small style="color:#8b949e">Web: ${b.web_url || "нет"} | OData: ${b.odata_url || "нет"} | Пользователь: ${b.username || "нет"}</small>`;
      list.appendChild(card);
    });
  } catch (e) {}
}

function renderScanResults(summary) {
  document.getElementById("scanResults").style.display = "block";
  document.getElementById("statTotalIssues").textContent = summary.total_issues || 0;
  document.getElementById("statCritical").textContent = (summary.issues_by_severity?.CRITICAL || 0);
  document.getElementById("statHigh").textContent = (summary.issues_by_severity?.HIGH || 0);

  const statStatus = document.getElementById("statStatus");
  if (summary.passed) {
    statStatus.textContent = "PASSED";
    statStatus.style.color = "#3fb950";
  } else {
    statStatus.textContent = "FAIL";
    statStatus.style.color = "#f85149";
  }

  const list = document.getElementById("issuesList");
  list.innerHTML = "";

  if (!summary.issues || summary.issues.length === 0) {
    list.innerHTML = '<div class="card" style="color: #3fb950">✓ Уязвимостей и нарушений стандартов не обнаружено!</div>';
    return;
  }

  summary.issues.forEach(issue => {
    const card = document.createElement("div");
    card.className = `issue-card ${issue.severity}`;
    card.innerHTML = `
      <div class="issue-header">
        <span class="badge badge-${issue.severity}">${issue.severity}</span>
        <span class="issue-rule">${issue.rule_id}</span>
        <span class="issue-msg">${issue.message}</span>
      </div>
      <div class="issue-location">Файл: ${issue.file_path} : строка ${issue.line}</div>
      ${issue.code_fragment ? `<div class="issue-code">${escapeHtml(issue.code_fragment)}</div>` : ''}
      <div class="issue-rec"><strong>Рекомендация:</strong> ${issue.recommendation || ''}</div>
    `;
    list.appendChild(card);
  });
}

function renderTestRunnerResult(result) {
  const monitor = document.getElementById("runnerResults");
  monitor.style.display = "block";
  const badge = document.getElementById("monitorStatusBadge");
  badge.textContent = result.is_success ? "УСПЕШНО" : "ОШИБКА";
  badge.style.background = result.is_success ? "#3fb950" : "#f85149";
  badge.style.color = "#fff";

  const list = document.getElementById("monitorStepList");
  list.innerHTML = "";

  (result.scenarios || []).forEach(sc => {
    const scTitle = document.createElement("h4");
    scTitle.style.marginTop = "10px";
    scTitle.textContent = `${sc.title} (${sc.status}) - ${sc.duration_ms} мс`;
    list.appendChild(scTitle);

    if (sc.error) {
      const errDiv = document.createElement("div");
      errDiv.style.color = "#f85149";
      errDiv.style.margin = "4px 0";
      errDiv.textContent = `Ошибка: ${sc.error}`;
      list.appendChild(errDiv);
    }

    (sc.step_results || []).forEach(st => {
      const row = document.createElement("div");
      row.className = "step-item";
      row.innerHTML = `<span class="step-mark ${st.status}">${st.status === 'PASSED' ? '✓' : st.status === 'FAILED' ? '✗' : '-'}</span>
      <span><strong>Шаг ${st.step_index}:</strong> ${escapeHtml(st.description)} (${st.duration_ms} мс)</span>`;
      list.appendChild(row);
    });
  });
}

function escapeHtml(text) {
  const map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' };
  return String(text).replace(/[&<>"']/g, m => map[m]);
}
