const IDENTIFIER = /^[\p{L}_][\p{L}\p{N}_]*(?:\/[\p{L}_][\p{L}\p{N}_]*)*$/u;

/** Read-only OData client. The publication URL is explicitly supplied per call. */
export class ErpODataClient {
  constructor({ serviceUrl = "", fetchImpl = globalThis.fetch } = {}) {
    this.serviceUrl = normalize(serviceUrl);
    this.fetchImpl = fetchImpl;
  }

  async status({ remote = false } = {}) {
    const status = { configured: Boolean(this.serviceUrl), service_url: this.serviceUrl, read_only: true };
    if (remote) { const entities = await this.listEntities(); status.reachable = true; status.entity_count = entities.count; }
    return status;
  }

  async listEntities() {
    const xml = await this.request("$metadata", "application/xml");
    const entities = [...xml.matchAll(/<(?:(?:\w+):)?EntitySet\b([^>]*)\/?\s*>/giu)].map((match) => {
      const attributes = Object.fromEntries([...match[1].matchAll(/([\w:.-]+)\s*=\s*["']([^"']*)["']/gu)].map((part) => [part[1], part[2]]));
      return { name: attributes.Name, entity_type: attributes.EntityType || "" };
    }).filter((item) => item.name).sort((a, b) => a.name.localeCompare(b.name, "ru"));
    return { service_url: this.serviceUrl, count: entities.length, entities };
  }

  async query({ entity, select = [], filter = "", order_by = "", expand = "", top = 100, skip = 0 }) {
    if (!IDENTIFIER.test(entity) || select.some((field) => !IDENTIFIER.test(field))) throw new Error("Имя OData-сущности или поля содержит недопустимые символы.");
    if (!Number.isInteger(top) || top < 1 || top > 1000 || !Number.isInteger(skip) || skip < 0) throw new Error("Недопустимый диапазон чтения OData.");
    const params = new URLSearchParams({ $format: "json", $top: String(top), $skip: String(skip) });
    if (select.length) params.set("$select", select.join(",")); if (filter) params.set("$filter", filter); if (order_by) params.set("$orderby", order_by); if (expand) params.set("$expand", expand);
    const payload = JSON.parse(await this.request(`${encodeURIComponent(entity)}?${params}`, "application/json"));
    const legacy = payload.d; const rows = payload.value ?? legacy?.results ?? legacy;
    if (!Array.isArray(rows)) throw new Error("OData JSON не содержит коллекцию данных.");
    return { entity, count: rows.length, rows, next_link: payload["@odata.nextLink"] || legacy?.__next || "", request: { select, filter, order_by, expand, top, skip } };
  }

  async request(relative, accept) {
    if (!this.serviceUrl) throw new Error("Сначала выберите публикацию 1С.");
    const response = await this.fetchImpl(`${this.serviceUrl}/${relative}`, { method: "GET", headers: { Accept: accept, DataServiceVersion: "3.0", MaxDataServiceVersion: "3.0" } });
    if (!response.ok) throw new Error(`OData 1С вернул HTTP ${response.status}.`);
    return response.text();
  }
}

function normalize(value) {
  if (!value) return ""; const url = new URL(value);
  if (!["http:", "https:"].includes(url.protocol) || url.username || url.password || url.search || url.hash) throw new Error("Некорректный адрес публикации OData.");
  return url.href.replace(/\/+$/u, "");
}
