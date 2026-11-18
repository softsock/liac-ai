const property = /^\s*\{\s*("(?:[^"\\\x00-\x1f]|\\(?:["\\/bfnrt]|u[\da-fA-F]{4}))*")\s*:\s*"/;
const stringBody = /^(?:[^"\\\x00-\x1f]|\\(?:["\\/bfnrt]|u[\da-fA-F]{4}))*/;

function messageParts(raw) {
    const match = property.exec(raw);
    if (!match || JSON.parse(match[1]) !== "message") return null;
    const tail = raw.slice(match[0].length);
    const body = stringBody.exec(tail)[0];
    return { body, afterBody: tail.slice(body.length) };
}

export class SpeakStream {
    #raw = new Map();
    #index;
    #emitted = 0;

    raw(index) {
        return this.#raw.get(index) ?? "";
    }

    push(index, name, chunk) {
        const raw = this.raw(index) + chunk;
        if (raw.length > 16_384) throw new Error("Tool arguments too large");
        this.#raw.set(index, raw);
        if (name !== "speak") return "";
        this.#index ??= index;
        if (this.#index !== index) return "";
        const part = messageParts(raw);
        if (!part) return "";
        const prefix = JSON.parse('"' + part.body + '"').replace(/[\uD800-\uDBFF]$/, "");
        if (!prefix.isWellFormed()) return "";
        const delta = prefix.slice(this.#emitted);
        this.#emitted = prefix.length;
        return delta;
    }
}

export function completedArguments(name, raw, final) {
    let parsed;
    try {
        parsed = JSON.parse(raw);
    } catch {
        return null;
    }
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed) ||
        !final || typeof final !== "object" || Array.isArray(final)) return null;
    if (name === "speak" && /^"\s*\}\s*$/.test(messageParts(raw)?.afterBody ?? "") &&
        typeof parsed.message === "string" && parsed.message.trim() && parsed.message.isWellFormed() &&
        Object.keys(final).length === 1 && parsed.message === final.message) return parsed;
    if (name === "stay_silent" && !Object.keys(parsed).length && !Object.keys(final).length) return parsed;
    return null;
}
