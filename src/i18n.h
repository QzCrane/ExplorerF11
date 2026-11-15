// SPDX-License-Identifier: MIT
//
// Minimal runtime localisation.
//
// Every user-visible string is written as T(L"中文", L"English") at the point of
// use. That keeps both translations in one place (the line that shows them) and
// avoids a separate resource file for a single-binary utility. Language is
// chosen once at start-up:
//
//   --lang zh|en            highest priority, one run only
//   EXPLORERF11_LANG=zh|en  for scripts and portable installs
//   display language        GetUserDefaultUILanguage(); Chinese -> zh, else en
//
// English is the fallback, so an unknown locale never mixes the two languages.
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

inline bool ParseLang(const wchar_t *s, Lang *out) {
    if (!s) return false;
    if (_wcsicmp(s, L"zh") == 0 || _wcsicmp(s, L"zh-cn") == 0 ||
        _wcsicmp(s, L"zh-hans") == 0 || _wcsicmp(s, L"chinese") == 0) {
        *out = Lang::Zh;
        return true;
    }
    if (_wcsicmp(s, L"en") == 0 || _wcsicmp(s, L"en-us") == 0 ||
        _wcsicmp(s, L"english") == 0) {
        *out = Lang::En;
        return true;
    }
    return false;
}

inline void DetectLang() {
    wchar_t env[16] = {0};
    Lang lang = Lang::En;
    if (GetEnvironmentVariableW(L"EXPLORERF11_LANG", env, 16) &&
        ParseLang(env, &lang)) {
        SetLang(lang);
        return;
    }
    // Three signals, because they disagree often enough to matter: a machine
    // with an English UI and a Chinese region should still read as Chinese.
    wchar_t locale[LOCALE_NAME_MAX_LENGTH] = {0};
    if (GetUserDefaultLocaleName(locale, LOCALE_NAME_MAX_LENGTH) &&
        wcsncmp(locale, L"zh", 2) == 0) {
        SetLang(Lang::Zh);
        return;
    }
    if (PRIMARYLANGID(GetUserDefaultUILanguage()) == LANG_CHINESE ||
        PRIMARYLANGID(GetSystemDefaultUILanguage()) == LANG_CHINESE) {
        SetLang(Lang::Zh);
        return;
    }
    SetLang(Lang::En);
}

// The only localisation primitive. zh is shown when the UI language is Chinese.
inline const wchar_t *T(const wchar_t *zh, const wchar_t *en) {
    return IsZh() ? zh : en;
}

}  // namespace ef11

using ef11::T;

#endif  // EF11_I18N_H
