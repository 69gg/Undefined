/*
 * WebUI 日志过滤工具
 * - 统一日志等级与同义词
 * - 按时间戳起始行聚合多行日志记录
 * - 统一处理关键词、等级和时间范围过滤
 */

(function (global) {
    "use strict";

    // 日志等级定义（按严重度由低到高）
    const LOG_LEVEL_DEFS = {
        debug: {
            rank: 0,
            aliases: ["debug"],
        },
        info: {
            rank: 1,
            aliases: ["info"],
        },
        warn: {
            rank: 2,
            aliases: ["warn", "warning"],
        },
        error: {
            rank: 3,
            aliases: ["error", "fatal", "critical", "exception"],
        },
    };

    // 结构化日志中常见的等级格式
    const STRUCTURED_LEVEL_PATTERNS = [
        /\[(?<level>[A-Z]+)\]/,
        /\s-\s(?<level>[A-Z]+)\s-\s/,
        /\b(levelname|level)\s*[:=]\s*(?<level>[A-Z]+)\b/i,
    ];

    // 日志起始行的时间戳判断（兼容逗号/点毫秒）
    const TIMESTAMP_RE = /^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?/;

    function buildLevelAliasMap() {
        const map = new Map();
        Object.keys(LOG_LEVEL_DEFS).forEach((level) => {
            const aliases = LOG_LEVEL_DEFS[level].aliases || [];
            aliases.forEach((alias) => {
                map.set(alias.toLowerCase(), level);
            });
            map.set(level.toLowerCase(), level);
        });
        return map;
    }

    const LEVEL_ALIAS_MAP = buildLevelAliasMap();

    function buildTokenRegex() {
        const tokens = Array.from(LEVEL_ALIAS_MAP.keys());
        const unique = Array.from(new Set(tokens));
        unique.sort((a, b) => b.length - a.length);
        return new RegExp(`\\b(${unique.join("|")})\\b`, "i");
    }

    const LEVEL_TOKEN_RE = buildTokenRegex();

    function getLogLevels() {
        const levels = Object.keys(LOG_LEVEL_DEFS).sort(
            (a, b) => LOG_LEVEL_DEFS[b].rank - LOG_LEVEL_DEFS[a].rank,
        );
        return ["all", ...levels];
    }

    function stripAnsi(text) {
        return text.replace(/\x1b\[[0-9;]*m/g, "");
    }

    function normalizeLogLevel(rawLevel) {
        if (!rawLevel) return null;
        const key = String(rawLevel).toLowerCase();
        return LEVEL_ALIAS_MAP.get(key) || null;
    }

    function parseLogLevel(line) {
        if (!line) return null;
        const cleaned = stripAnsi(line);

        for (const pattern of STRUCTURED_LEVEL_PATTERNS) {
            const match = cleaned.match(pattern);
            const level = match?.groups?.level || match?.[1];
            const normalized = normalizeLogLevel(level);
            if (normalized) return normalized;
        }

        const tokenMatch = cleaned.match(LEVEL_TOKEN_RE);
        if (tokenMatch) {
            return normalizeLogLevel(tokenMatch[1]);
        }

        return null;
    }

    function parseLogTimestamp(line) {
        if (!line) return null;
        const match = stripAnsi(line).match(TIMESTAMP_RE);
        if (!match) return null;
        const timestamp = new Date(
            match[0].replace(" ", "T").replace(",", "."),
        ).getTime();
        return Number.isFinite(timestamp) ? timestamp : null;
    }

    function splitLogRecords(lines) {
        const records = [];
        let current = null;

        lines.forEach((line) => {
            const cleaned = stripAnsi(line);
            const isStart = TIMESTAMP_RE.test(cleaned);

            if (isStart && current && current.lines.length) {
                records.push(current);
                current = null;
            }

            if (!current) {
                current = {
                    lines: [],
                    level: null,
                    timestamp: isStart ? parseLogTimestamp(line) : null,
                };
            }

            const detected = parseLogLevel(line);
            if (detected && !current.level) {
                current.level = detected;
            }

            current.lines.push(line);
        });

        if (current && current.lines.length) {
            records.push(current);
        }

        return records;
    }

    function parseLogRecords(raw) {
        if (!raw) return [];
        const lines = raw.split(/\r?\n/);
        return splitLogRecords(lines).filter((record) =>
            record.lines.some((line) => line.length > 0),
        );
    }

    function getLevelRank(level) {
        return LOG_LEVEL_DEFS[level]?.rank ?? -1;
    }

    function shouldKeepRecord(recordLevel, options) {
        const target = options.level || "all";
        if (target === "all") return true;
        if (!recordLevel) return false;

        if (!options.gte) {
            return recordLevel === target;
        }

        return getLevelRank(recordLevel) >= getLevelRank(target);
    }

    function normalizeFilterTimestamp(value) {
        if (typeof value === "number") {
            return Number.isFinite(value) ? value : 0;
        }
        if (typeof value !== "string" || !value.trim()) return 0;
        const numeric = Number(value);
        if (Number.isFinite(numeric)) return numeric;
        const parsed = Date.parse(value);
        return Number.isFinite(parsed) ? parsed : 0;
    }

    function recordMatchesFilters(record, options) {
        if (!shouldKeepRecord(record.level, options)) return false;

        const query = String(options.query || "")
            .trim()
            .toLowerCase();
        const searchableText = stripAnsi(record.lines.join("\n")).toLowerCase();
        if (query && !searchableText.includes(query)) {
            return false;
        }

        const timeFrom = normalizeFilterTimestamp(options.timeFrom);
        const timeTo = normalizeFilterTimestamp(options.timeTo);
        if (record.timestamp !== null) {
            if (timeFrom && record.timestamp < timeFrom) return false;
            if (timeTo && record.timestamp > timeTo) return false;
        }
        return true;
    }

    function filterLogRecords(raw, options) {
        const safeOptions = options || {};
        const records = parseLogRecords(raw);
        const filtered = records.filter((record) =>
            recordMatchesFilters(record, safeOptions),
        );
        return {
            records: filtered,
            total: records.length,
            matched: filtered.length,
        };
    }

    function filterLogLines(raw, options) {
        const result = filterLogRecords(raw, options);
        return {
            filtered: result.records.flatMap((record) => record.lines),
            total: result.total,
            matched: result.matched,
        };
    }

    global.LogsController = {
        LOG_LEVEL_DEFS,
        LOG_LEVELS: getLogLevels(),
        parseLogLevel,
        parseLogTimestamp,
        parseLogRecords,
        filterLogRecords,
        filterLogLines,
        getLevelRank,
    };
})(window);
