import { describe, expect, test } from "vitest";
import { createTranslator, defaultLocale, dictionaries, t } from "./index";

describe("i18n", () => {
	test("defaults to Chinese and exposes matching English keys", () => {
		expect(defaultLocale).toBe("zh-CN");
		expect(t("app.title")).toBe("Undefined Chat");
		expect(t("composer.placeholder")).toBe("给 Undefined 发送消息");

		const zhKeys = Object.keys(dictionaries["zh-CN"]).sort();
		const enKeys = Object.keys(dictionaries.en).sort();
		expect(enKeys).toEqual(zhKeys);
		expect(dictionaries.en["composer.placeholder"]).toBe("Message Undefined");
	});

	test("falls back to the key when a translation is missing", () => {
		const translate = createTranslator("zh-CN");

		expect(translate("missing.key")).toBe("missing.key");
	});
});
