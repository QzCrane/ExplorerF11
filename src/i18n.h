// SPDX-License-Identifier: MIT
//
// Runtime localisation, without a resource DLL.
//
// Every user-visible string is written as T(L"中文", L"English") at the point of
// use. Both translations therefore sit on the line that shows them, a missing
// translation is a compile-time hole rather than a runtime lookup failure, and
// a single-binary utility stays a single binary.
//
// Language resolution, highest priority first:
//
//   --lang zh|en            this run only
//   EXPLORERF11_LANG=zh|en  this run only (scripts, portable copies)
//   Language value          the choice made in the tray menu, persisted
//   system locale           GetUserDefaultLocaleName / UI language
//
// The first two override the stored choice because they are explicit,
// per-invocation instructions; the stored choice exists so that a tray click
// survives a restart. English is the fallback for anything unrecognised, so the
// UI never mixes the two languages.
//
// Persistence rule (mirrors the registry policy in config.h): the stored value
// is written only when the chosen language differs from the system language,
// and is deleted when the choice returns to it. A user who never touches the
// language menu leaves no value behind.
#ifndef EF11_I18N_H
#define EF11_I18N_H

#include <windows.h>

namespace ef11 {

enum class Lang { Zh, En };

inline Lang &LangState() {
    static Lang lang = Lang::Zh;
    return lang;
}

inline void SetLang(Lang lang) { LangState() = lang; }
inline Lang GetLang()            { return LangState(); }
inline bool IsZh()               { return LangState() == Lang::Zh; }

// Accepts the BCP-47 tags a user is likely to type, plus the bare names.
inline bool ParseLang(const wchar_t *s, Lang *out) {
    if (!s) return false;
    if (_wcsicmp(s, L"zh") == 0 || _wcsicmp(s, L"zh-cn") == 0 ||
        _wcsicmp(s, L"zh-hans") == 0 || _wcsicmp(s, L"zh-sg") == 0 ||
        _wcsicmp(s, L"chinese") == 0) {
        *out = Lang::Zh;
        return true;
    }
    if (_wcsicmp(s, L"en") == 0 || _wcsicmp(s, L"en-us") == 0 ||
        _wcsicmp(s, L"en-gb") == 0 || _wcsicmp(s, L"english") == 0) {
        *out = Lang::En;
        return true;
    }
    return false;
}

// Canonical on-disk form, used for the stored Language value.
inline const wchar_t *LangTag(Lang lang) { return lang == Lang::Zh ? L"zh" : L"en"; }

// EXPLORERF11_LANG, when set to something valid.
inline bool EnvLang(Lang *out) {
    wchar_t env[32] = {0};
    if (!GetEnvironmentVariableW(L"EXPLORERF11_LANG", env, 32)) return false;
    return ParseLang(env, out);
}

// What this machine speaks, ignoring the stored choice and the environment.
// Three signals, because they disagree often enough to matter: a machine with
// an English UI and a Chinese region should still read as Chinese.
inline Lang LocaleLang() {
    wchar_t locale[LOCALE_NAME_MAX_LENGTH] = {0};
    if (GetUserDefaultLocaleName(locale, LOCALE_NAME_MAX_LENGTH) &&
        _wcsnicmp(locale, L"zh", 2) == 0)
        return Lang::Zh;
    if (PRIMARYLANGID(GetUserDefaultUILanguage()) == LANG_CHINESE ||
        PRIMARYLANGID(GetSystemDefaultUILanguage()) == LANG_CHINESE)
        return Lang::Zh;
    return Lang::En;
}

// The default a persisted choice is compared against: environment first (it is
// what the user would see with no stored value), then the machine locale.
inline Lang DefaultLang() {
    Lang l;
    return EnvLang(&l) ? l : LocaleLang();
}

// The only localisation primitive. zh is shown when the UI language is Chinese.
inline const wchar_t *T(const wchar_t *zh, const wchar_t *en) {
    return IsZh() ? zh : en;
}

}  // namespace ef11

using ef11::T;

#endif  // EF11_I18N_H
