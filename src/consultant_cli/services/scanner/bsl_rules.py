from __future__ import annotations

import re
from typing import Callable, List, Optional
from consultant_cli.services.scanner.models import IssueCategory, ScanIssue, Severity


class BSLRule:
    """Base class for static analysis rules checking BSL code."""

    def __init__(
        self,
        rule_id: str,
        category: IssueCategory,
        severity: Severity,
        message: str,
        recommendation: str = "",
    ) -> None:
        self.rule_id = rule_id
        self.category = category
        self.severity = severity
        self.message = message
        self.recommendation = recommendation

    def analyze(self, file_path: str, lines: list[str]) -> list[ScanIssue]:
        raise NotImplementedError


class RegexLineRule(BSLRule):
    """Rule matching single lines against regular expressions, skipping comments."""

    def __init__(
        self,
        rule_id: str,
        category: IssueCategory,
        severity: Severity,
        pattern: str,
        message: str,
        recommendation: str = "",
        case_sensitive: bool = False,
    ) -> None:
        super().__init__(rule_id, category, severity, message, recommendation)
        flags = 0 if case_sensitive else re.IGNORECASE
        self.regex = re.compile(pattern, flags)

    def analyze(self, file_path: str, lines: list[str]) -> list[ScanIssue]:
        issues: list[ScanIssue] = []
        for idx, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("//"):
                continue
            # remove line-end comments
            code_part = stripped.split("//", 1)[0].strip()
            if not code_part:
                continue
            match = self.regex.search(code_part)
            if match:
                issues.append(
                    ScanIssue(
                        rule_id=self.rule_id,
                        category=self.category,
                        severity=self.severity,
                        message=self.message,
                        file_path=file_path,
                        line=idx,
                        col=match.start() + 1,
                        code_fragment=line.strip()[:140],
                        recommendation=self.recommendation,
                    )
                )
        return issues


class DynamicExecutionRule(BSLRule):
    """SEC001: Detects dangerous dynamic code execution with concatenated parameters."""

    def __init__(self) -> None:
        super().__init__(
            rule_id="SEC001",
            category=IssueCategory.SECURITY,
            severity=Severity.CRITICAL,
            message="Опасный вызов Выполнить() / Вычислить() с динамической конкатенацией строк.",
            recommendation="Избегайте выполнения динамического кода из внешних источников. Передавайте вызовы через фиксированные алгоритмы или проверяйте входные данные по белому списку.",
        )
        self.regex = re.compile(r"\b(Выполнить|Вычислить|Execute|Eval)\s*\((.*)\)", re.IGNORECASE)

    def analyze(self, file_path: str, lines: list[str]) -> list[ScanIssue]:
        issues: list[ScanIssue] = []
        for idx, line in enumerate(lines, 1):
            clean = line.split("//", 1)[0].strip()
            if not clean:
                continue
            match = self.regex.search(clean)
            if match:
                arg = match.group(2).strip()
                # Check if argument contains string concatenation or variable instead of static string literal
                has_concat = "+" in arg or "СтрШаблон" in arg or "StrTemplate" in arg
                is_variable = bool(re.match(r"^[a-zA-Zа-яА-Я_][a-zA-Zа-яА-Я0-9_]*$", arg))
                if has_concat or is_variable:
                    issues.append(
                        ScanIssue(
                            rule_id=self.rule_id,
                            category=self.category,
                            severity=self.severity,
                            message=self.message,
                            file_path=file_path,
                            line=idx,
                            col=match.start() + 1,
                            code_fragment=line.strip()[:140],
                            recommendation=self.recommendation,
                        )
                    )
        return issues


class QueryInjectionRule(BSLRule):
    """SEC002: Detects dynamic string concatenation into 1C query text instead of query parameters."""

    def __init__(self) -> None:
        super().__init__(
            rule_id="SEC002",
            category=IssueCategory.SECURITY,
            severity=Severity.HIGH,
            message="Потенциальная инъекция в запрос 1С: конкатенация строк в тексте запроса.",
            recommendation="Используйте параметры запроса (&Параметр) и метод Запрос.УстановитьПараметр() вместо конкатенации строковых переменных.",
        )
        # Matches: .Текст = ... + or .Текст = .Текст +
        self.regex = re.compile(
            r"\b(Текст|Text)\s*(\+?=|=.*\+)\s*.*",
            re.IGNORECASE,
        )

    def analyze(self, file_path: str, lines: list[str]) -> list[ScanIssue]:
        issues: list[ScanIssue] = []
        for idx, line in enumerate(lines, 1):
            clean = line.split("//", 1)[0].strip()
            if not clean:
                continue
            # Look for lines setting query text with variable concatenation
            if ("Запрос.Текст" in clean or "Query.Text" in clean) and "+" in clean:
                # Check if right-hand side has identifiers not enclosed in quotes
                parts = clean.split("+")
                has_var = False
                for p in parts[1:]:
                    p_clean = p.strip().rstrip(";")
                    if p_clean and not (p_clean.startswith('"') and p_clean.endswith('"')):
                        has_var = True
                        break
                if has_var:
                    issues.append(
                        ScanIssue(
                            rule_id=self.rule_id,
                            category=self.category,
                            severity=self.severity,
                            message=self.message,
                            file_path=file_path,
                            line=idx,
                            col=1,
                            code_fragment=line.strip()[:140],
                            recommendation=self.recommendation,
                        )
                    )
        return issues


class PrivilegedModeRule(BSLRule):
    """SEC003: Detects Unrestricted Privileged Mode usage without rights check."""

    def __init__(self) -> None:
        super().__init__(
            rule_id="SEC003",
            category=IssueCategory.SECURITY,
            severity=Severity.HIGH,
            message="Включение привилегированного режима без предшествующей проверки прав доступа.",
            recommendation="Перед УстановитьПривилегированныйРежим(Истина) проверяйте права пользователя (например, Пользователи.ЭтоПолноправныйПользователь() или ПравоДоступа).",
        )
        self.regex = re.compile(
            r"\b(УстановитьПривилегированныйРежим|SetPrivilegedMode)\s*\(\s*(Истина|True)\s*\)",
            re.IGNORECASE,
        )
        self.auth_check_regex = re.compile(
            r"(ПравоДоступа|ЭтоПолноправныйПользователь|CheckAccess|IsFullUser|РольДоступна)",
            re.IGNORECASE,
        )

    def analyze(self, file_path: str, lines: list[str]) -> list[ScanIssue]:
        issues: list[ScanIssue] = []
        for idx, line in enumerate(lines, 1):
            clean = line.split("//", 1)[0].strip()
            if not clean:
                continue
            match = self.regex.search(clean)
            if match:
                # Check previous 25 lines for any rights/roles verification
                start_window = max(0, idx - 26)
                window = "".join(lines[start_window:idx - 1])
                if not self.auth_check_regex.search(window):
                    issues.append(
                        ScanIssue(
                            rule_id=self.rule_id,
                            category=self.category,
                            severity=self.severity,
                            message=self.message,
                            file_path=file_path,
                            line=idx,
                            col=match.start() + 1,
                            code_fragment=line.strip()[:140],
                            recommendation=self.recommendation,
                        )
                    )
        return issues


class HardcodedCredentialsRule(BSLRule):
    """SEC004: Detects hardcoded passwords, tokens, API keys in string literals."""

    def __init__(self) -> None:
        super().__init__(
            rule_id="SEC004",
            category=IssueCategory.SECURITY,
            severity=Severity.MEDIUM,
            message="Обнаружен возможный хардкод пароля, токена или ключа API в открытом коде.",
            recommendation="Выносите пароли и ключи в защищенные параметры сеанса, константы с ограниченным доступом или переменные окружения.",
        )
        self.regex = re.compile(
            r"""(?i)\b(пароль|password|api[_-]?key|secret[_-]?token|bearer\s+[a-z0-9_\-\.]+)\s*=\s*["']([^"'\s]{4,})["']""",
            re.IGNORECASE,
        )

    def analyze(self, file_path: str, lines: list[str]) -> list[ScanIssue]:
        issues: list[ScanIssue] = []
        for idx, line in enumerate(lines, 1):
            clean = line.split("//", 1)[0].strip()
            if not clean:
                continue
            match = self.regex.search(clean)
            if match:
                val = match.group(2)
                # Ignore dummy/template values like "123", "password", ""
                if val.lower() not in {"", "123", "12345", "test", "пароль"}:
                    issues.append(
                        ScanIssue(
                            rule_id=self.rule_id,
                            category=self.category,
                            severity=self.severity,
                            message=self.message,
                            file_path=file_path,
                            line=idx,
                            col=match.start() + 1,
                            code_fragment=line.strip()[:140],
                            recommendation=self.recommendation,
                        )
                    )
        return issues


class ManagedLockInPostingRule(BSLRule):
    """LCK001: Validates that ОбработкаПроведения explicitly sets БлокировкаДанных before writing records."""

    def __init__(self) -> None:
        super().__init__(
            rule_id="LCK001",
            category=IssueCategory.LOCKING,
            severity=Severity.HIGH,
            message="Отсутствует явная управляемая блокировка (БлокировкаДанных) в процедуре ОбработкаПроведения.",
            recommendation="При проведении документов в режиме управляемых блокировок обязательно используйте БлокировкаДанных перед чтением остатков и записью движений.",
        )
        self.posting_proc_regex = re.compile(r"\b(Процедура|Procedure)\s+ОбработкаПроведения\s*\(", re.IGNORECASE)
        self.end_proc_regex = re.compile(r"\b(КонецПроцедуры|EndProcedure)\b", re.IGNORECASE)
        self.lock_regex = re.compile(r"\b(БлокировкаДанных|DataLock)\b", re.IGNORECASE)
        self.recordset_write_regex = re.compile(r"\.(Записать|Записывать|Write)\s*\(", re.IGNORECASE)

    def analyze(self, file_path: str, lines: list[str]) -> list[ScanIssue]:
        issues: list[ScanIssue] = []
        in_posting = False
        posting_start_line = 0
        has_lock = False
        has_record_write = False

        for idx, line in enumerate(lines, 1):
            clean = line.split("//", 1)[0].strip()
            if not clean:
                continue

            if not in_posting:
                if self.posting_proc_regex.search(clean):
                    in_posting = True
                    posting_start_line = idx
                    has_lock = False
                    has_record_write = False
            else:
                if self.lock_regex.search(clean):
                    has_lock = True
                if self.recordset_write_regex.search(clean):
                    has_record_write = True
                if self.end_proc_regex.search(clean):
                    if has_record_write and not has_lock:
                        issues.append(
                            ScanIssue(
                                rule_id=self.rule_id,
                                category=self.category,
                                severity=self.severity,
                                message=self.message,
                                file_path=file_path,
                                line=posting_start_line,
                                col=1,
                                code_fragment=lines[posting_start_line - 1].strip()[:140],
                                recommendation=self.recommendation,
                            )
                        )
                    in_posting = False

        return issues


class QueryInLoopRule(BSLRule):
    """PERF001: Detects queries executed inside loops."""

    def __init__(self) -> None:
        super().__init__(
            rule_id="PERF001",
            category=IssueCategory.PERFORMANCE,
            severity=Severity.HIGH,
            message="Выполнение запроса 1С внутри цикла (антипаттерн N+1).",
            recommendation="Формируйте массив или таблицу значений с отборами и выполняйте один пакетный запрос с условием 'ГДЕ Поле В (&МассивЗначений)'.",
        )
        self.loop_start_regex = re.compile(r"\b(Для|Для каждого|Пока|For|For each|While)\b.*\b(Цикл|Do)\b", re.IGNORECASE)
        self.loop_end_regex = re.compile(r"\b(КонецЦикла|EndDo)\b", re.IGNORECASE)
        self.query_exec_regex = re.compile(r"\b(Запрос|Query)\s*\.\s*(Выполнить|ВыполнитьПакет|Execute|ExecuteBatch)\s*\(", re.IGNORECASE)

    def analyze(self, file_path: str, lines: list[str]) -> list[ScanIssue]:
        issues: list[ScanIssue] = []
        loop_depth = 0

        for idx, line in enumerate(lines, 1):
            clean = line.split("//", 1)[0].strip()
            if not clean:
                continue

            if self.loop_start_regex.search(clean):
                loop_depth += 1
            if loop_depth > 0 and self.query_exec_regex.search(clean):
                issues.append(
                    ScanIssue(
                        rule_id=self.rule_id,
                        category=self.category,
                        severity=self.severity,
                        message=self.message,
                        file_path=file_path,
                        line=idx,
                        col=1,
                        code_fragment=line.strip()[:140],
                        recommendation=self.recommendation,
                    )
                )
            if self.loop_end_regex.search(clean):
                loop_depth = max(0, loop_depth - 1)

        return issues


class ServerCallInClientLoopRule(BSLRule):
    """PERF002: Detects loops in &НаКлиенте invoking server methods."""

    def __init__(self) -> None:
        super().__init__(
            rule_id="PERF002",
            category=IssueCategory.PERFORMANCE,
            severity=Severity.HIGH,
            message="Серверные вызовы в цикле на клиенте (&НаКлиенте).",
            recommendation="Передавайте на сервер всю коллекцию данных и обрабатывайте её за один серверный вызов.",
        )
        self.client_directive = re.compile(r"^&НаКлиенте\b|^&AtClient\b", re.IGNORECASE)
        self.server_directive = re.compile(r"^&НаСервере\b|^&AtServer\b", re.IGNORECASE)
        self.loop_start_regex = re.compile(r"\b(Для|Для каждого|Пока|For|For each|While)\b.*\b(Цикл|Do)\b", re.IGNORECASE)
        self.loop_end_regex = re.compile(r"\b(КонецЦикла|EndDo)\b", re.IGNORECASE)
        self.end_proc_regex = re.compile(r"\b(КонецПроцедуры|КонецФункции|EndProcedure|EndFunction)\b", re.IGNORECASE)

    def analyze(self, file_path: str, lines: list[str]) -> list[ScanIssue]:
        issues: list[ScanIssue] = []
        current_context = ""
        loop_depth = 0

        for idx, line in enumerate(lines, 1):
            clean = line.split("//", 1)[0].strip()
            if not clean:
                continue

            if self.client_directive.search(clean):
                current_context = "client"
            elif self.server_directive.search(clean):
                current_context = "server"
            elif self.end_proc_regex.search(clean):
                current_context = ""
                loop_depth = 0

            if current_context == "client":
                if self.loop_start_regex.search(clean):
                    loop_depth += 1
                elif self.loop_end_regex.search(clean):
                    loop_depth = max(0, loop_depth - 1)

                if loop_depth > 0:
                    # check for common server module calls like ОбщегоНазначения, РаботаСНоменклатурой etc.
                    if re.search(r"\b(ОбщегоНазначения|Модуль|Сервер|Server|DataProcessor|ДокументОбъект)\.", clean, re.IGNORECASE):
                        issues.append(
                            ScanIssue(
                                rule_id=self.rule_id,
                                category=self.category,
                                severity=self.severity,
                                message=self.message,
                                file_path=file_path,
                                line=idx,
                                col=1,
                                code_fragment=line.strip()[:140],
                                recommendation=self.recommendation,
                            )
                        )

        return issues


class EmptyExceptionHandlerRule(BSLRule):
    """STD002: Detects empty exception handlers."""

    def __init__(self) -> None:
        super().__init__(
            rule_id="STD002",
            category=IssueCategory.STANDARDS,
            severity=Severity.LOW,
            message="Пустой блок Исключение...КонецПопытки без обработки или логирования ошибки.",
            recommendation="Записывайте ошибки в ЖурналРегистрации или информируйте пользователя через ВызватьИсключение / ПоказатьОшибку.",
        )
        self.except_regex = re.compile(r"\b(Исключение|Except)\b", re.IGNORECASE)
        self.end_try_regex = re.compile(r"\b(КонецПопытки|EndTry)\b", re.IGNORECASE)

    def analyze(self, file_path: str, lines: list[str]) -> list[ScanIssue]:
        issues: list[ScanIssue] = []
        in_except = False
        except_line = 0
        has_content = False

        for idx, line in enumerate(lines, 1):
            clean = line.split("//", 1)[0].strip()
            if not clean:
                continue

            if self.except_regex.search(clean):
                in_except = True
                except_line = idx
                has_content = False
            elif in_except:
                if self.end_try_regex.search(clean):
                    if not has_content:
                        issues.append(
                            ScanIssue(
                                rule_id=self.rule_id,
                                category=self.category,
                                severity=self.severity,
                                message=self.message,
                                file_path=file_path,
                                line=except_line,
                                col=1,
                                code_fragment=lines[except_line - 1].strip()[:140],
                                recommendation=self.recommendation,
                            )
                        )
                    in_except = False
                else:
                    has_content = True

        return issues




class V8StdExportMethodCommentRule(BSLRule):
    """v8std:comment-api - Экспортные методы должны иметь документирующую шапку с описанием параметров."""

    def __init__(self) -> None:
        super().__init__(
            rule_id="v8std:comment-api",
            category=IssueCategory.STANDARDS,
            severity=Severity.LOW,
            message="Экспортная процедура/функция не имеет описания назначения и параметров по стандарту v8std.",
            recommendation="Добавьте перед экспортным методом комментарий по шаблону: // Описание метода... // Параметры: //   ИмяПараметра - Тип - Описание.",
        )
        self.export_proc_regex = re.compile(
            r"\b(Процедура|Функция|Procedure|Function)\s+([a-zA-Zа-яА-Я0-9_]+)\s*\(.*\)\s+Экспорт\b",
            re.IGNORECASE,
        )

    def analyze(self, file_path: str, lines: list[str]) -> list[ScanIssue]:
        issues: list[ScanIssue] = []
        for idx, line in enumerate(lines, 1):
            clean = line.split("//", 1)[0].strip()
            if not clean:
                continue
            match = self.export_proc_regex.search(clean)
            if match:
                # Check previous 3 lines for comment lines
                has_comment = False
                for prev_idx in range(max(0, idx - 4), idx - 1):
                    if lines[prev_idx].strip().startswith("//"):
                        has_comment = True
                        break
                if not has_comment:
                    issues.append(
                        ScanIssue(
                            rule_id=self.rule_id,
                            category=self.category,
                            severity=self.severity,
                            message=f"{self.message} Метод: {match.group(2)}",
                            file_path=file_path,
                            line=idx,
                            col=match.start() + 1,
                            code_fragment=line.strip()[:140],
                            recommendation=self.recommendation,
                        )
                    )
        return issues


class V8StdNamingRule(BSLRule):
    """v8std:naming - Именование переменных: запрет однобуквенных переменных (кроме счетчиков циклов) и латиницы в именах переменных."""

    def __init__(self) -> None:
        super().__init__(
            rule_id="v8std:naming",
            category=IssueCategory.STANDARDS,
            severity=Severity.LOW,
            message="Нарушение стандарта именования v8std: использование однобуквенной неинформативной переменной.",
            recommendation="Используйте осмысленные имена переменных на русском языке в нотации PascalCase (например, ДанныеСтроки, а не Д или S).",
        )
        self.bad_var_regex = re.compile(
            r"\b([абвгдежзийклмнопрстуфхцчшщэюяa-z])\s*=\s*[^=]",
            re.IGNORECASE,
        )

    def analyze(self, file_path: str, lines: list[str]) -> list[ScanIssue]:
        issues: list[ScanIssue] = []
        for idx, line in enumerate(lines, 1):
            clean = line.split("//", 1)[0].strip()
            if not clean:
                continue
            # Ignore loop counters like Для Сч = 1 or For i = 1
            if re.search(r"\b(Для|For)\s+([a-zA-Zа-яА-Я0-9_]+)\s*=", clean, re.IGNORECASE):
                continue
            match = self.bad_var_regex.search(clean)
            if match:
                var_name = match.group(1)
                # Ignore well-known exceptions if any
                issues.append(
                    ScanIssue(
                        rule_id=self.rule_id,
                        category=self.category,
                        severity=self.severity,
                        message=f"{self.message} Переменная '{var_name}'.",
                        file_path=file_path,
                        line=idx,
                        col=match.start() + 1,
                        code_fragment=line.strip()[:140],
                        recommendation=self.recommendation,
                    )
                )
        return issues


class V8StdVirtualTableParamsRule(BSLRule):
    """v8std:virtual-tables-params - Запрет отборов в ГДЕ для виртуальных таблиц вместо параметров."""

    def __init__(self) -> None:
        super().__init__(
            rule_id="v8std:virtual-tables-params",
            category=IssueCategory.PERFORMANCE,
            severity=Severity.HIGH,
            message="Фильтрация виртуальной таблицы в секции ГДЕ вместо параметров таблицы (стандарт v8std).",
            recommendation="Всегда передавайте условия отбора в параметры виртуальной таблицы (например, РегистрНакопления.Остатки(Период, Условие)), чтобы СУБД отбирала данные на уровне индексов.",
        )
        self.unparam_vt = re.compile(
            r"\b(РегистрНакопления|РегистрБухгалтерии|РегистрСведений)\.[a-zA-Zа-яА-Я0-9_]+\.(Остатки|Обороты|ОстаткиИОбороты|СрезПоследних|СрезПервых)\s*\(\s*\)",
            re.IGNORECASE,
        )

    def analyze(self, file_path: str, lines: list[str]) -> list[ScanIssue]:
        issues: list[ScanIssue] = []
        for idx, line in enumerate(lines, 1):
            clean = line.split("//", 1)[0].strip()
            if not clean:
                continue
            match = self.unparam_vt.search(clean)
            if match:
                issues.append(
                    ScanIssue(
                        rule_id=self.rule_id,
                        category=self.category,
                        severity=self.severity,
                        message=self.message,
                        file_path=file_path,
                        line=idx,
                        col=match.start() + 1,
                        code_fragment=line.strip()[:140],
                        recommendation=self.recommendation,
                    )
                )
        return issues

def get_default_rules() -> list[BSLRule]:
    """Returns the comprehensive set of built-in BSL security and standards rules."""
    return [
        DynamicExecutionRule(),
        QueryInjectionRule(),
        PrivilegedModeRule(),
        HardcodedCredentialsRule(),
        ManagedLockInPostingRule(),
        QueryInLoopRule(),
        ServerCallInClientLoopRule(),
        EmptyExceptionHandlerRule(),
        RegexLineRule(
            rule_id="SEC005",
            category=IssueCategory.SECURITY,
            severity=Severity.HIGH,
            pattern=r"\b(КомандаСистемы|ЗапуститьПриложение|WScript\.Shell)\s*\(",
            message="Использование внешних команд операционной системы без валидации параметров.",
            recommendation="Ограничивайте запуск внешних приложений строгими шаблонами и экранируйте параметры.",
        ),
        RegexLineRule(
            rule_id="STD001",
            category=IssueCategory.STANDARDS,
            severity=Severity.LOW,
            pattern=r"\bСообщить\s*\(",
            message="Использование устаревшего метода Сообщить() в интерфейсном коде.",
            recommendation="Используйте ПоказатьОповещениеПользователя() или ОбщегоНазначенияКлиентСервер.СообщитьПользователю().",
        ),
        V8StdExportMethodCommentRule(),
        V8StdNamingRule(),
        V8StdVirtualTableParamsRule(),
        RegexLineRule(
            rule_id="v8std:unconditional-server-context",
            category=IssueCategory.PERFORMANCE,
            severity=Severity.MEDIUM,
            pattern=r"^&НаСервере\b|^&AtServer\b",
            message="Использование директивы &НаСервере. По стандарту v8std рекомендуется использовать &НаСервереБезКонтекста, если нет изменения реквизитов формы.",
            recommendation="Замените на &НаСервереБезКонтекста и передавайте нужные параметры явно для снижения сетевого трафика формы.",
        ),
    ]
