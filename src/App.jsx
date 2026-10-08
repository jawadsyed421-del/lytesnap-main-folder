import { useState, useEffect, useRef } from "react";
import lytesnapIcon from "./icons/lytesnap.svg";

const TOPICS = [
  { id: "gaming",  emoji: "🎮", name: "Gaming",   desc: "Minecraft, Fortnite, tutorials",  color: "#AB47BC" },
  { id: "sports",  emoji: "⚽", name: "Sports",   desc: "NBA, soccer, workouts",            color: "#42A5F5" },
  { id: "makeup",  emoji: "💄", name: "Makeup",   desc: "Skincare, makeup, fashion",        color: "#EC407A" },
  { id: "drama",   emoji: "🎬", name: "Drama",    desc: "TV series, romance, thriller",     color: "#FFA726" },
  { id: "finance",    emoji: "📈", name: "Finance",    desc: "Stocks, investing, crypto",           color: "#26A69A" },
  { id: "democrat",   emoji: "🫏", name: "Democrat",   desc: "Liberal politics, progressive news",  color: "#1565C0" },
  { id: "republican", emoji: "🐘", name: "Republican", desc: "Conservative politics, MAGA, Trump",  color: "#C62828" },
];


// Maps topic id → main_topic + narrow_topics for the Python backend
const TOPIC_MAP = {
  gaming:  { main: "Gaming",  narrow: ["Minecraft gameplay", "Fortnite highlights", "GTA 5 gameplay", "Call of Duty warzone"] },
  sports:  { main: "Sports",  narrow: ["NFL football", "NBA highlights", "soccer skills", "workout motivation"] },
  makeup:  { main: "Makeup",  narrow: ["skincare routine", "makeup tutorial", "natural beauty", "beauty product review"] },
  drama:   { main: "Drama",   narrow: ["Netflix series recommendations", "TV show review", "romance drama series", "thriller TV show"] },
  finance:    { main: "Finance",    narrow: ["stock market investing", "personal finance tips", "index funds", "real estate investing"] },
  democrat:   { main: "Democrat",   narrow: ["Democratic Party news", "progressive politics", "liberal commentary", "Biden policy"] },
  republican: { main: "Republican", narrow: ["Republican Party news", "conservative politics", "Trump rally", "MAGA news"] },
};

const STATUS = [
  "Replacing triggers...", "Unaddicting the feed...", "Removing rewards...",
  "The craving fades...", "New patterns forming...", "Filling with good content...",
  "Almost there...",
];

// ─── Sunrise Background ───────────────────────────────────────────────────────
const SunriseBg = ({ phase = "dawn", hideMoon = false, hideSun = false }) => {
  const gradients = {
    night:    "linear-gradient(180deg, #0B0B2E 0%, #1B1464 30%, #2D1B69 60%, #1B1464 100%)",
    dawn:     "linear-gradient(180deg, #2D1B69 0%, #6B3FA0 25%, #C85C8E 50%, #F4845F 75%, #F7B267 100%)",
    sunrise:  "linear-gradient(180deg, #4A2270 0%, #E8637C 30%, #F4845F 55%, #F7B267 75%, #FCD581 100%)",
    day:      "linear-gradient(180deg, #667EEA 0%, #88A0F0 30%, #F7B267 70%, #FCD581 100%)",
    complete: "linear-gradient(180deg, #43A5DC 0%, #67C6E3 30%, #FCD581 60%, #FFE8A3 100%)",
  };
  const isNight = phase === "night";
  return (
    <div style={{ position: "absolute", inset: 0, background: gradients[phase], transition: "background 2s ease" }}>
      {/* Moon */}
      <div style={{
        position: "absolute", bottom: isNight ? "12%" : "-30%",
        left: "50%", transform: "translateX(-50%)",
        width: 60, height: 60, borderRadius: "50%",
        background: "radial-gradient(circle at 40% 35%, #FFFDE7, #F5F0CC, #E8E0B0)",
        boxShadow: isNight ? "0 0 30px rgba(255,253,231,0.4), 0 0 60px rgba(255,253,231,0.15)" : "none",
        opacity: (isNight && !hideMoon) ? 1 : 0, transition: "all 2s ease", overflow: "hidden",
      }}>
        <div style={{ position: "absolute", top: 12, left: 18, width: 10, height: 10, borderRadius: "50%", background: "rgba(200,190,160,0.25)" }} />
        <div style={{ position: "absolute", top: 28, left: 30, width: 7, height: 7, borderRadius: "50%", background: "rgba(200,190,160,0.2)" }} />
      </div>
      {/* Stars */}
      {[{t:"10%",l:"15%",s:2},{t:"8%",l:"75%",s:3},{t:"22%",l:"85%",s:2},{t:"15%",l:"30%",s:1.5},{t:"25%",l:"60%",s:2},{t:"5%",l:"50%",s:1.5}].map((st, i) => (
        <div key={i} style={{ position: "absolute", top: st.t, left: st.l, width: st.s, height: st.s, borderRadius: "50%", background: "#fff", opacity: isNight ? 0.5 : 0, transition: "opacity 2s", animation: isNight ? `twinkle ${2+i*0.5}s ease-in-out infinite alternate` : "none" }} />
      ))}
      {/* Sun */}
      <div style={{
        position: "absolute", bottom: (phase === "sunrise" || phase === "complete") ? "12%" : phase === "day" ? "20%" : "-15%",
        left: "50%", transform: "translateX(-50%)",
        width: 70, height: 70, borderRadius: "50%",
        background: "radial-gradient(circle at 40% 35%, #FFF7E0, #FCD581, #F4A55F, #E8637C)",
        boxShadow: !isNight ? "0 0 40px rgba(252,213,129,0.5)" : "none",
        opacity: (isNight || hideSun) ? 0 : (phase === "dawn" ? 0.3 : 1),
        transition: "all 2s ease",
      }} />
    </div>
  );
};

// ─── Pill ─────────────────────────────────────────────────────────────────────
const Pill = ({ color = "blue", size = 1, glowing = false }) => {
  const isB = color === "blue";
  const w = 72 * size, h = 30 * size;
  return (
    <div style={{
      width: w, height: h, borderRadius: h / 2, display: "flex", overflow: "hidden",
      boxShadow: glowing ? `0 4px 20px ${isB ? "rgba(92,156,230,0.5)" : "rgba(232,93,117,0.5)"}` : "0 2px 10px rgba(0,0,0,0.12)",
      transition: "box-shadow 0.4s",
    }}>
      <div style={{ flex: 1, background: `linear-gradient(160deg, ${isB ? "#88BDF0" : "#F08898"}, ${isB ? "#5C9CE6" : "#E85D75"}, ${isB ? "#3A7BD5" : "#C94058"})`, position: "relative" }}>
        <div style={{ position: "absolute", top: h*0.17, left: h*0.3, width: w*0.28, height: h*0.22, borderRadius: h, background: "rgba(255,255,255,0.4)" }} />
      </div>
      <div style={{ width: 1.5, background: "rgba(255,255,255,0.2)" }} />
      <div style={{ flex: 1, background: `linear-gradient(160deg, ${isB ? "#7DB0EA" : "#EB7D90"}, ${isB ? "#4A8AD8" : "#D14D68"}, ${isB ? "#2E6BC0" : "#B33550"})` }} />
    </div>
  );
};

// ─── Session Pill (morphs blue→red) ──────────────────────────────────────────
const SessionPill = ({ progress }) => {
  const p = Math.min(progress / 100, 1);
  const r = Math.round(92 + 140 * p), g = Math.round(156 - 63 * p), b = Math.round(230 - 113 * p);
  const main = `rgb(${r},${g},${b})`;
  const light = `rgb(${Math.min(r+35,255)},${Math.min(g+35,255)},${Math.min(b+35,255)})`;
  const dark = `rgb(${Math.max(r-35,0)},${Math.max(g-35,0)},${Math.max(b-35,0)})`;
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 6 }}>
      <div style={{
        width: 110, height: 46, borderRadius: 23, display: "flex", overflow: "hidden",
        animation: "pill-spin 5s linear infinite",
        boxShadow: `0 6px 24px rgba(${r},${g},${b},0.35)`, transition: "box-shadow 0.5s",
      }}>
        <div style={{ flex: 1, background: `linear-gradient(160deg, ${light}, ${main}, ${dark})`, position: "relative", transition: "background 0.5s" }}>
          <div style={{ position: "absolute", top: 7, left: 10, width: 32, height: 11, borderRadius: 8, background: "rgba(255,255,255,0.4)" }} />
        </div>
        <div style={{ width: 1.5, background: "rgba(255,255,255,0.2)" }} />
        <div style={{ flex: 1, background: `linear-gradient(160deg, ${light}, ${main} 60%, ${dark})`, opacity: 0.88, transition: "background 0.5s" }} />
      </div>
      <div style={{ width: 60, height: 8, borderRadius: "50%", background: `radial-gradient(ellipse, rgba(${r},${g},${b},0.25), transparent 70%)`, animation: "shadow-breathe 5s ease-in-out infinite" }} />
    </div>
  );
};

// ─── NavBar ───────────────────────────────────────────────────────────────────
const NavBar = ({ screen, onNav }) => (
  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "36px 20px 14px", position: "relative", zIndex: 10, WebkitAppRegion: "drag" }}>
    <div onClick={() => onNav("home")} style={{ cursor: "pointer", WebkitAppRegion: "no-drag", lineHeight: 0 }}>
      <svg width="27" height="41" viewBox="0 0 43 65" fill="none" xmlns="http://www.w3.org/2000/svg"
        style={{ filter: "drop-shadow(0 1px 4px rgba(0,0,0,0.15))" }}>
        <path fillRule="evenodd" clipRule="evenodd" d="M11.1819 38.9403C10.5581 37.692 9.45004 35.4744 12.4747 32.9515C13.2968 32.2658 16.2008 30.3786 19.7613 28.0648C24.1891 25.1874 29.6321 21.6502 33.3493 18.9433C34.0061 18.465 34.4441 17.7526 34.5951 16.9543L37.5086 1.55298C37.7269 0.39907 36.4301 -0.434259 35.4712 0.243734L4.94597 21.8269C2.37602 23.5845 -2.00786 27.6968 1.03564 33.2206C3.4768 37.6513 11.4437 39.5134 11.4437 39.5134C11.3896 39.3559 11.2935 39.1636 11.1819 38.9403ZM31.53 25.4505C32.1537 26.6988 33.2618 28.9164 30.2371 31.4393C29.415 32.125 26.511 34.0122 22.9505 36.326C18.5228 39.2034 13.0797 42.7406 9.36254 45.4475C8.70576 45.9258 8.26777 46.6382 8.11675 47.4365L5.20321 62.8378C4.98492 63.9917 6.28172 64.8251 7.24062 64.1471L37.7659 42.5639C40.3358 40.8063 44.7197 36.694 41.6762 31.1702C39.235 26.7395 31.2681 24.8774 31.2681 24.8774C31.3223 25.0349 31.4184 25.2272 31.53 25.4505Z" fill="#FCD581"/>
      </svg>
    </div>
    <div style={{ display: "flex", gap: 6, WebkitAppRegion: "no-drag" }}>
      {[
        ["topics", <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><rect x="1" y="2" width="14" height="2" rx="1" fill="white"/><rect x="1" y="7" width="14" height="2" rx="1" fill="white"/><rect x="1" y="12" width="14" height="2" rx="1" fill="white"/><polyline points="1,2.5 3,4.5 5,2" stroke="white" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" fill="none"/></svg>],
        ["schedule", <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><circle cx="8" cy="8" r="6.5" stroke="white" strokeWidth="1.5"/><path d="M8 4.5V8.5L10.5 10" stroke="white" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg>],
      ].map(([s, icon]) => (
        <button key={s} onClick={() => onNav(s)} style={{
          width: 34, height: 34, borderRadius: 12,
          background: screen === s ? "rgba(255,255,255,0.25)" : "rgba(255,255,255,0.1)",
          border: "none", cursor: "pointer",
          display: "flex", alignItems: "center", justifyContent: "center",
          backdropFilter: "blur(8px)", transition: "background 0.2s",
        }}>{icon}</button>
      ))}
    </div>
  </div>
);

// ─── API Key (optional user override) ─────────────────────────────────────────
const ApiKeySettings = ({ variant = "dark" }) => {
  const light = variant === "light";
  const [open, setOpen] = useState(false);
  const [hasCustom, setHasCustom] = useState(false);
  const [keyInput, setKeyInput] = useState("");
  const [msg, setMsg] = useState("");

  useEffect(() => {
    window.lytesnap?.getApiKeyStatus().then(r => setHasCustom(r?.hasCustomKey ?? false));
  }, []);

  const save = async () => {
    setMsg("");
    const res = await window.lytesnap?.setUserApiKey(keyInput);
    if (res?.error) { setMsg(res.error); return; }
    setHasCustom(true);
    setKeyInput("");
    setMsg("Custom API key saved.");
  };

  const clear = async () => {
    await window.lytesnap?.clearUserApiKey();
    setHasCustom(false);
    setKeyInput("");
    setMsg("Using default API key.");
  };

  const muted = light ? "#999" : "rgba(255,255,255,0.45)";
  const panelBg = light ? "#f5f5f5" : "rgba(255,255,255,0.12)";
  const inputBg = light ? "#fff" : "rgba(0,0,0,0.15)";
  const inputColor = light ? "#2D3436" : "#fff";
  const inputBorder = light ? "#ddd" : "rgba(255,255,255,0.2)";

  return (
    <div style={{ marginTop: light ? 0 : 16, maxWidth: 320, width: "100%" }}>
      <button onClick={() => setOpen(o => !o)} style={{
        background: "none", border: "none", cursor: "pointer",
        fontSize: 12, color: muted, fontWeight: 500,
      }}>
        {open ? "▾ Hide API key settings" : "▸ Use your own API key (optional)"}
      </button>
      {open && (
        <div style={{ marginTop: 10, padding: "14px 16px", background: panelBg, borderRadius: 14, backdropFilter: light ? "none" : "blur(8px)", textAlign: "left" }}>
          <p style={{ fontSize: 11, color: muted, margin: "0 0 10px 0", lineHeight: 1.5 }}>
            Leave blank to use the built-in key. Your key is stored securely on this device.
          </p>
          <input
            type="password"
            value={keyInput}
            onChange={e => setKeyInput(e.target.value)}
            placeholder="sk-ant-..."
            style={{
              width: "100%", boxSizing: "border-box", padding: "10px 12px",
              borderRadius: 10, border: `1px solid ${inputBorder}`,
              background: inputBg, color: inputColor, fontSize: 13,
            }}
          />
          <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
            <button onClick={save} disabled={!keyInput.trim()} style={{
              flex: 1, padding: "10px", border: "none", borderRadius: 10, cursor: "pointer",
              background: keyInput.trim() ? "linear-gradient(135deg, #F4845F, #F7B267)" : (light ? "#e0e0e0" : "rgba(255,255,255,0.15)"),
              color: keyInput.trim() ? "#fff" : muted, fontSize: 12, fontWeight: 600,
            }}>Save key</button>
            {hasCustom && (
              <button onClick={clear} style={{
                padding: "10px 12px", border: `1px solid ${inputBorder}`, borderRadius: 10,
                background: "transparent", color: light ? "#666" : "rgba(255,255,255,0.7)", fontSize: 12, cursor: "pointer",
              }}>Reset</button>
            )}
          </div>
          {hasCustom && !msg && (
            <p style={{ fontSize: 11, color: muted, margin: "8px 0 0 0" }}>Custom API key active</p>
          )}
          {msg && <p style={{ fontSize: 11, color: light ? "#666" : "rgba(255,255,255,0.65)", margin: "8px 0 0 0" }}>{msg}</p>}
        </div>
      )}
    </div>
  );
};

// ─── Setup ────────────────────────────────────────────────────────────────────
const SetupScreen = ({ onComplete, onSignIn, hasPrefs }) => {
  const [loggedIn, setLoggedIn] = useState(null); // null = loading

  useEffect(() => {
    window.lytesnap?.authStatus().then(r => setLoggedIn(r?.loggedIn ?? false));
  }, []);

  if (loggedIn === null) return (
    <div style={{ position: "relative", minHeight: 820, display: "flex", alignItems: "center", justifyContent: "center" }}>
      <SunriseBg phase="night" hideMoon={true} />
    </div>
  );

  return (
    <div style={{ position: "relative", minHeight: 820, display: "flex", flexDirection: "column", justifyContent: "center", alignItems: "center", padding: "40px 24px" }}>
      <SunriseBg phase="night" hideMoon={true} />
      <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 40, WebkitAppRegion: "drag", zIndex: 10 }} />
      <div style={{ position: "relative", zIndex: 1, textAlign: "center" }}>
        <div style={{ margin: "0 auto 20px", width: 54, animation: "sun-breathe 4s ease-in-out infinite",
          filter: "drop-shadow(0 0 16px rgba(252,213,129,0.6))" }}>
          <img src={lytesnapIcon} alt="LyteSnap" style={{ width: 54, display: "block" }} />
        </div>
        <h1 style={{ fontSize: 30, fontWeight: 700, color: "#fff", margin: "0 0 8px 0", textShadow: "0 2px 8px rgba(0,0,0,0.15)" }}>lytesnap</h1>
        <p style={{ fontSize: 15, color: "rgba(255,255,255,0.65)", margin: "0 0 44px 0" }}>Unaddict the feed. Enjoy something better.</p>

        {loggedIn ? (
          <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 14 }}>
            <button onClick={onComplete} style={{
              padding: "16px 48px",
              background: "linear-gradient(135deg, #F4845F, #F7B267)",
              color: "#fff", border: "none", borderRadius: 20,
              fontSize: 16, fontWeight: 700, cursor: "pointer",
              boxShadow: "0 4px 20px rgba(244,132,95,0.4)",
            }}>{hasPrefs ? "Change Your Feed →" : "Get Started →"}</button>
            <button onClick={onSignIn} style={{
              background: "none", border: "none", cursor: "pointer",
              fontSize: 13, color: "rgba(255,255,255,0.35)", fontWeight: 500,
            }}>Switch account</button>
            <ApiKeySettings />
          </div>
        ) : (
          <div style={{ padding: "28px 24px", background: "rgba(255,255,255,0.95)", borderRadius: 24, boxShadow: "0 8px 32px rgba(0,0,0,0.1)", maxWidth: 320 }}>
            <h3 style={{ fontSize: 18, fontWeight: 700, color: "#2D3436", margin: "0 0 8px 0" }}>Let's get started</h3>
            <p style={{ fontSize: 13, color: "#999", margin: "0 0 24px 0", lineHeight: 1.6 }}>Sign into the YouTube account that needs help. Google Chrome is required.</p>
            <button onClick={onSignIn} style={{
              width: "100%", padding: "15px",
              background: "linear-gradient(135deg, #F4845F, #F7B267)",
              color: "#fff", border: "none", borderRadius: 16,
              fontSize: 15, fontWeight: 700, cursor: "pointer",
              boxShadow: "0 4px 15px rgba(244,132,95,0.35)",
            }}>Open Chrome →</button>
            <div style={{ marginTop: 14 }}>
              <ApiKeySettings variant="light" />
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

// ─── Treatment / Topics ───────────────────────────────────────────────────────
const TreatmentScreen = ({ mode = 'unaddict', selected, onToggle, onStart, onNav }) => {
  const [hover, setHover] = useState(null);
  return (
    <div style={{ position: "relative", minHeight: 820 }}>
      <SunriseBg phase={mode === 'unaddict' ? "dawn" : "sunrise"} />
      <div style={{ position: "relative", zIndex: 1 }}>
        <NavBar screen="topics" onNav={onNav} />
        <div style={{ padding: "0 20px 24px" }}>
          <div style={{ marginBottom: 8 }}>
            <h2 style={{ fontSize: 22, fontWeight: 700, color: "#fff", margin: "0 0 4px 0", textShadow: "0 2px 6px rgba(0,0,0,0.1)" }}>{mode === 'unaddict' ? "What do they hate watching?" : "What do you love watching?"}</h2>
            <p style={{ fontSize: 13, color: "rgba(255,255,255,0.55)", margin: "0 0 16px 0" }}>{mode === 'unaddict' ? "Pick topics they'd never click. We'll flood the feed with these." : "Pick topics you actually enjoy. We'll fill your feed with these."}</p>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 20 }}>
            {TOPICS.map(t => {
              const sel = selected.includes(t.id);
              const hov = hover === t.id;
              const filled = sel || hov;
              return (
                <button key={t.id} onClick={() => onToggle(t.id)}
                  onMouseEnter={() => setHover(t.id)} onMouseLeave={() => setHover(null)}
                  style={{
                    display: "flex", alignItems: "center", gap: 14,
                    padding: "14px 16px", width: "100%",
                    background: filled ? t.color : "rgba(255,255,255,0.8)",
                    border: "2px solid transparent", borderRadius: 18,
                    cursor: "pointer", textAlign: "left", transition: "all 0.35s",
                    backdropFilter: "blur(10px)",
                    boxShadow: filled ? `0 8px 24px ${t.color}40` : "0 2px 8px rgba(0,0,0,0.04)",
                    transform: hov ? "translateY(-2px) scale(1.02)" : "scale(1)",
                  }}>
                  <div style={{
                    width: 42, height: 42, borderRadius: 14,
                    background: filled ? "rgba(255,255,255,0.25)" : "#F5F5F5",
                    border: filled ? "2px solid rgba(255,255,255,0.7)" : "2px solid transparent",
                    display: "flex", alignItems: "center", justifyContent: "center",
                    fontSize: 20, transition: "all 0.3s",
                  }}>{t.emoji}</div>
                  <div style={{ flex: 1 }}>
                    <span style={{ fontSize: 15, fontWeight: 600, color: filled ? "#fff" : "#2D3436", transition: "color 0.35s" }}>{t.name}</span>
                    <br />
                    <span style={{ fontSize: 12, color: filled ? "rgba(255,255,255,0.75)" : "#aaa", transition: "color 0.35s" }}>{t.desc}</span>
                  </div>
                  <div style={{
                    width: 22, height: 22, borderRadius: 7,
                    border: `2px solid ${filled ? "rgba(255,255,255,0.5)" : "#ddd"}`,
                    background: sel ? "rgba(255,255,255,0.3)" : "transparent",
                    display: "flex", alignItems: "center", justifyContent: "center",
                    transition: "all 0.25s",
                  }}>
                    {sel && <span style={{ color: "#fff", fontSize: 12, fontWeight: 800 }}>✓</span>}
                  </div>
                </button>
              );
            })}
          </div>
          {selected.length > 0 && (
            <button onClick={onStart} style={{
              width: "100%", padding: "16px",
              background: "linear-gradient(135deg, #E05535, #D4842F)",
              color: "#fff",
              border: "none", borderRadius: 18, fontSize: 15, fontWeight: 700,
              cursor: "pointer", transition: "all 0.3s",
              boxShadow: "0 4px 15px rgba(224,85,53,0.4)",
            }}>
              {mode === 'unaddict' ? "Choose treatment phase →" : "Save enjoy topics →"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
};

// ─── Phase Selection ──────────────────────────────────────────────────────────
const PhaseScreen = ({ topics, onChoose, onNav }) => {
  const [hover, setHover] = useState(null);
  const names = TOPICS.filter(t => topics.includes(t.id)).map(t => t.name).join(" & ");
  return (
    <div style={{ position: "relative", minHeight: 820 }}>
      <SunriseBg phase={hover === "unaddict" ? "night" : hover === "enjoy" ? "sunrise" : "dawn"} />
      <div style={{ position: "relative", zIndex: 1 }}>
        <NavBar screen="phase" onNav={onNav} />
        <div style={{ padding: "0 20px 28px", textAlign: "center" }}>
          <h2 style={{ fontSize: 22, fontWeight: 700, color: "#fff", margin: "0 0 6px 0", textShadow: "0 2px 6px rgba(0,0,0,0.15)" }}>How should we help?</h2>
          <p style={{ fontSize: 13, color: "rgba(255,255,255,0.5)", margin: "0 0 24px 0" }}>Flooding with: {names}</p>
          <div style={{ display: "flex", gap: 14, marginBottom: 24 }}>
            {/* Phase 1: Unaddict */}
            <button onClick={() => onChoose("unaddict")}
              onMouseEnter={() => setHover("unaddict")} onMouseLeave={() => setHover(null)}
              style={{
                flex: 1, padding: "24px 14px 20px",
                background: hover === "unaddict" ? "linear-gradient(160deg, #E85D75, #C94058)" : "rgba(255,255,255,0.92)",
                border: "2px solid transparent", borderRadius: 22,
                cursor: "pointer", textAlign: "center", transition: "all 0.4s",
                boxShadow: hover === "unaddict" ? "0 12px 40px rgba(232,93,117,0.35)" : "0 4px 16px rgba(0,0,0,0.06)",
                transform: hover === "unaddict" ? "translateY(-4px) scale(1.02)" : "none",
              }}>
              <div style={{ display: "flex", justifyContent: "center", marginBottom: 12, transform: hover === "unaddict" ? "scale(1.1)" : "scale(1)", transition: "transform 0.3s" }}>
                <Pill color="red" size={1} glowing={hover === "unaddict"} />
              </div>
              <div style={{ fontSize: 11, fontWeight: 700, color: hover === "unaddict" ? "rgba(255,255,255,0.6)" : "#bbb", letterSpacing: 1.5, marginBottom: 4 }}>PHASE 1</div>
              <div style={{ fontSize: 18, fontWeight: 700, color: hover === "unaddict" ? "#fff" : "#2D3436", marginBottom: 6, transition: "color 0.4s" }}>Unaddict</div>
              <div style={{ fontSize: 12, color: hover === "unaddict" ? "rgba(255,255,255,0.8)" : "#999", lineHeight: 1.5, transition: "color 0.4s" }}>The feed fills with what they hate. They put the phone down.</div>
            </button>
            {/* Phase 2: Enjoy */}
            <button onClick={() => onChoose("enjoy")}
              onMouseEnter={() => setHover("enjoy")} onMouseLeave={() => setHover(null)}
              style={{
                flex: 1, padding: "24px 14px 20px",
                background: hover === "enjoy" ? "linear-gradient(160deg, #5C9CE6, #3A7BD5)" : "rgba(255,255,255,0.92)",
                border: "2px solid transparent", borderRadius: 22,
                cursor: "pointer", textAlign: "center", transition: "all 0.4s",
                boxShadow: hover === "enjoy" ? "0 12px 40px rgba(58,123,213,0.35)" : "0 4px 16px rgba(0,0,0,0.06)",
                transform: hover === "enjoy" ? "translateY(-4px) scale(1.02)" : "none",
              }}>
              <div style={{ display: "flex", justifyContent: "center", marginBottom: 12, transform: hover === "enjoy" ? "scale(1.1)" : "scale(1)", transition: "transform 0.3s" }}>
                <Pill color="blue" size={1} glowing={hover === "enjoy"} />
              </div>
              <div style={{ fontSize: 11, fontWeight: 700, color: hover === "enjoy" ? "rgba(255,255,255,0.6)" : "#bbb", letterSpacing: 1.5, marginBottom: 4 }}>PHASE 2</div>
              <div style={{ fontSize: 18, fontWeight: 700, color: hover === "enjoy" ? "#fff" : "#2D3436", marginBottom: 6, transition: "color 0.4s" }}>Enjoy</div>
              <div style={{ fontSize: 12, color: hover === "enjoy" ? "rgba(255,255,255,0.8)" : "#999", lineHeight: 1.5, transition: "color 0.4s" }}>Fill the feed with healthy content. New rewards, new habits. A new sunrise.</div>
            </button>
          </div>
          <p style={{
            fontSize: 13, fontWeight: 500,
            color: hover ? "rgba(255,255,255,0.85)" : "rgba(255,255,255,0.3)",
            transition: "color 0.4s", minHeight: 36, lineHeight: 1.5,
          }}>
            {hover === "unaddict" ? "The feed fills with what they hate. They put the phone down." : hover === "enjoy" ? "Then, we fill the void with content worth watching. New habits form naturally." : "\u00A0"}
          </p>
          <div style={{ padding: "12px 16px", background: "rgba(255,255,255,0.12)", borderRadius: 14, backdropFilter: "blur(8px)" }}>
            <p style={{ fontSize: 11, color: "rgba(255,255,255,0.5)", margin: 0, lineHeight: 1.5 }}>
              🧠 Based on B.F. Skinner's research: remove the variable rewards to extinguish the behavior, then introduce new reinforcement patterns.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
};

// ─── Auth ─────────────────────────────────────────────────────────────────────
const AuthScreen = ({ onComplete }) => {
  const [status, setStatus] = useState("Opening Chrome...");
  const [done, setDone] = useState(false);
  const startedRef = useRef(false);

  useEffect(() => {
    if (startedRef.current) return;
    startedRef.current = true;
    const api = window.lytesnap;
    api?.onAuthLog(line => {
      const clean = line.trim();
      if (clean) setStatus(clean.replace(/^\[auth\]\s*/, ""));
    });
    api?.onAuthComplete(({ success, error }) => {
      api.removeAllListeners("auth-log");
      api.removeAllListeners("auth-complete");
      if (success) { setDone(true); setTimeout(onComplete, 1500); }
      else setStatus(error || "Login failed. Please try again.");
    });
    api?.startAuth();
    return () => {
      api?.removeAllListeners("auth-log");
      api?.removeAllListeners("auth-complete");
    };
  }, []);

  return (
    <div style={{ position: "relative", minHeight: 820, display: "flex", flexDirection: "column", justifyContent: "center", alignItems: "center", padding: "40px 24px" }}>
      <SunriseBg phase={done ? "sunrise" : "night"} hideMoon={false} />
      <div style={{ position: "relative", zIndex: 1, textAlign: "center" }}>
        <div style={{
          width: 80, height: 80, borderRadius: "50%", margin: "0 auto 24px",
          background: done
            ? "radial-gradient(circle at 35% 35%, #FFF7E0, #FCD581, #F4A55F)"
            : "radial-gradient(circle at 40% 35%, #FFFDE7, #F5F0CC, #E8E0B0)",
          boxShadow: done ? "0 0 40px rgba(252,213,129,0.5)" : "0 0 30px rgba(255,253,231,0.4)",
          animation: "sun-breathe 4s ease-in-out infinite",
        }} />
        <h2 style={{ fontSize: 20, fontWeight: 700, color: "#fff", margin: "0 0 12px 0" }}>
          {done ? "You're signed in." : "Sign into YouTube"}
        </h2>
        <p style={{ fontSize: 14, color: "rgba(255,255,255,0.55)", margin: "0 0 32px 0", lineHeight: 1.6 }}>
          {done
            ? "Session saved. Ready to reshape the feed."
            : <>Chrome is opening. Log in, then<br />we'll save your session automatically.</>}
        </p>
        {done ? (
          <button onClick={onComplete} style={{
            padding: "16px 48px",
            background: "linear-gradient(135deg, #F4845F, #F7B267)",
            color: "#fff", border: "none", borderRadius: 20,
            fontSize: 16, fontWeight: 700, cursor: "pointer",
            boxShadow: "0 4px 20px rgba(244,132,95,0.4)",
          }}>Go to Home →</button>
        ) : (
          <div style={{ padding: "16px 20px", background: "rgba(255,255,255,0.1)", borderRadius: 14, backdropFilter: "blur(8px)", maxWidth: 300 }}>
            <p style={{ fontSize: 13, color: "rgba(255,255,255,0.7)", margin: 0, animation: "pulse-text 2s ease-in-out infinite" }}>{status}</p>
          </div>
        )}
      </div>
    </div>
  );
};

// ─── Home ─────────────────────────────────────────────────────────────────────
const HomeScreen = ({ topics, phase, lastResult, onRun, onChangeTopics, onChangePhase, onSwitchAccount, onNav }) => {
  const [runHover, setRunHover] = useState(false);
  const names = TOPICS.filter(t => topics.includes(t.id)).map(t => t.name).join(" & ");
  const isBreak = phase === "unaddict";

  return (
    <div style={{ position: "relative", minHeight: 820 }}>
      <SunriseBg phase={isBreak ? "dawn" : "sunrise"} hideSun={true} />
      <div style={{ position: "relative", zIndex: 1 }}>
        <NavBar screen="home" onNav={onNav} />
        <div style={{ padding: "0 20px 28px", textAlign: "center" }}>
          <div style={{
            width: 80, height: 80, borderRadius: "50%", margin: "16px auto 20px",
            background: "radial-gradient(circle at 35% 35%, #FFF7E0, #FCD581, #F4A55F)",
            boxShadow: "0 0 40px rgba(252,213,129,0.5)",
            animation: "sun-breathe 4s ease-in-out infinite",
          }} />
          <h2 style={{ fontSize: 22, fontWeight: 700, color: "#fff", margin: "0 0 4px 0", textShadow: "0 2px 6px rgba(0,0,0,0.15)" }}>{names}</h2>
          <p style={{ fontSize: 14, color: "rgba(255,255,255,0.55)", margin: "0 0 8px 0" }}>
            {isBreak ? "Phase 1 — Unaddict" : "Phase 2 — Enjoy"}
          </p>
          {lastResult && (
            <div style={{ padding: "10px 16px", background: "rgba(255,255,255,0.15)", borderRadius: 12, marginBottom: 32, display: "inline-block", backdropFilter: "blur(8px)" }}>
              <span style={{ fontSize: 13, color: "rgba(255,255,255,0.75)" }}>
                Last session: {Math.round(lastResult.before * 100)}% → {Math.round(lastResult.after * 100)}%
                {" "}({lastResult.after > lastResult.before ? "+" : ""}{Math.round((lastResult.after - lastResult.before) * 100)}%)
              </span>
            </div>
          )}
          <div style={{ marginBottom: 24 }}>
            <button onClick={onRun}
              onMouseEnter={() => setRunHover(true)} onMouseLeave={() => setRunHover(false)}
              style={{
                width: "100%", padding: "20px",
                background: runHover ? "linear-gradient(135deg, #E05535, #D4842F)" : "linear-gradient(135deg, #F4845F, #F7B267)",
                color: "#fff", border: "none", borderRadius: 20,
                fontSize: 18, fontWeight: 700, cursor: "pointer", transition: "all 0.35s",
                boxShadow: runHover ? "0 8px 30px rgba(244,132,95,0.4)" : "0 4px 15px rgba(244,132,95,0.3)",
                transform: runHover ? "translateY(-3px) scale(1.02)" : "none",
              }}>▶  Run Session</button>
          </div>
          <div style={{ display: "flex", justifyContent: "center", gap: 24 }}>
            <button onClick={onChangeTopics} style={{ background: "none", border: "none", cursor: "pointer", fontSize: 13, fontWeight: 500, color: "rgba(255,255,255,0.45)" }}>Change topics</button>
            <button onClick={onChangePhase} style={{ background: "none", border: "none", cursor: "pointer", fontSize: 13, fontWeight: 500, color: "rgba(255,255,255,0.45)" }}>Change phase</button>
            <button onClick={onSwitchAccount} style={{ background: "none", border: "none", cursor: "pointer", fontSize: 13, fontWeight: 500, color: "rgba(255,255,255,0.25)" }}>Switch account</button>
          </div>
        </div>
      </div>
    </div>
  );
};

// ─── Session ──────────────────────────────────────────────────────────────────
const SessionScreen = ({ topics, unaddictTopics = [], phase, scheduledStartTime, onBeforeScore, onStop, onComplete }) => {
  const SESSION_MINS = 45;
  const [elapsed, setElapsed] = useState(0);
  const [msgIdx, setMsgIdx] = useState(0);
  const [beforeScore, setBeforeScore] = useState(null);
  const [log, setLog] = useState([]);
  const [schedStatus, setSchedStatus] = useState(null);
  const startedRef = useRef(false);
  const timerRef = useRef(null);
  const startTimeRef = useRef(null);

  useEffect(() => {
    window.lytesnap?.getScheduleStatus().then(setSchedStatus);
    window.lytesnap?.onScheduleStatusChanged(setSchedStatus);
    return () => window.lytesnap?.removeAllListeners('schedule-status-changed');
  }, []);

  const progress = Math.min((elapsed / (SESSION_MINS * 60)) * 100, 100);
  const mins = Math.floor(elapsed / 60);
  const secs = elapsed % 60;
  const isBreak = phase === "unaddict";

  const skyPhase = isBreak
    ? (progress < 30 ? "night" : progress < 70 ? "dawn" : "sunrise")
    : (progress < 20 ? "dawn" : progress < 50 ? "sunrise" : progress < 80 ? "day" : "complete");

  useEffect(() => {
    if (startedRef.current) return;
    startedRef.current = true;

    const api = window.lytesnap;
    const activeTopics = phase === "unaddict" ? unaddictTopics : topics;
    const scoringTopic = activeTopics.filter(id => TOPIC_MAP[id]).map(id => TOPIC_MAP[id].main).join(' or ');

    if (scheduledStartTime) {
      // Scheduled session already running — anchor timer and score feed in parallel
      startTimeRef.current = new Date(scheduledStartTime).getTime();
      api?.scoreFeed(scoringTopic).then(r => {
        const score = r?.weighted_score ?? 0;
        setBeforeScore(score);
        onBeforeScore?.(score);
      });
      api?.getScheduleStatus().then(setSchedStatus);
    } else {
      // Manual session — score feed first, then start
      const sessionTopics = phase === "unaddict" ? unaddictTopics : topics;
      api?.scoreFeed(scoringTopic).then(r => {
        const score = r?.weighted_score ?? 0;
        setBeforeScore(score);
        onBeforeScore?.(score);
        api?.startSession({ topics: sessionTopics, phase }).then(res => {
          if (res?.error) console.error("[session error]", res.error);
          startTimeRef.current = Date.now();
          api?.getScheduleStatus().then(setSchedStatus);
        });
      });
    }

    // Listen for log lines
    api?.onSessionLog(line => setLog(prev => [...prev.slice(-50), line.trim()]));

    // Listen for completion
    api?.onSessionComplete(() => {
      clearInterval(timerRef.current);
      onComplete();
    });

    // Use Date.now() so throttled intervals still show accurate wall-clock time
    timerRef.current = setInterval(() => {
      if (startTimeRef.current) {
        setElapsed(Math.floor((Date.now() - startTimeRef.current) / 1000));
      }
    }, 1000);
    const msgTimer = setInterval(() => setMsgIdx(i => (i + 1) % STATUS.length), 3500);

    return () => {
      clearInterval(timerRef.current);
      clearInterval(msgTimer);
      api?.removeAllListeners("session-log");
      api?.removeAllListeners("session-complete");
    };
  }, []);

  return (
    <div style={{ position: "relative", minHeight: 820 }}>
      <SunriseBg phase={skyPhase} />
      <div style={{ position: "relative", zIndex: 1 }}>
        <div style={{ height: 40, WebkitAppRegion: "drag" }} />
        <div style={{ padding: "0 20px 24px" }}>
          <div style={{ textAlign: "center", marginBottom: 4 }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: "rgba(255,255,255,0.5)", letterSpacing: 1.5 }}>
              {isBreak ? "PHASE 1 — UNADDICTING" : "PHASE 2 — ENJOY"}
            </div>
            {schedStatus?.active && (
              <div style={{ fontSize: 10, color: "rgba(255,255,255,0.35)", marginTop: 3, letterSpacing: 0.8 }}>
                {schedStatus.phase === 'intensive'
                  ? `DAY ${(schedStatus.daysElapsed ?? 0) + 1} — INTENSIVE · EVERY 3 HRS`
                  : `DAY ${(schedStatus.daysElapsed ?? 0) + 1} — MAINTENANCE · ONCE/DAY`}
              </div>
            )}
          </div>
          {/* Timer */}
          <div style={{ textAlign: "center", marginBottom: 16 }}>
            <div style={{ position: "relative", display: "inline-block" }}>
              <svg width="140" height="140">
                <circle cx="70" cy="70" r="62" fill="rgba(255,255,255,0.1)" stroke="rgba(255,255,255,0.15)" strokeWidth="5" />
                <circle cx="70" cy="70" r="62" fill="none" stroke="rgba(255,255,255,0.9)" strokeWidth="5" strokeLinecap="round"
                  strokeDasharray={`${2*Math.PI*62}`} strokeDashoffset={`${2*Math.PI*62*(1-progress/100)}`}
                  style={{ transition: "stroke-dashoffset 1s linear", transform: "rotate(-90deg)", transformOrigin: "70px 70px", filter: "drop-shadow(0 0 6px rgba(255,255,255,0.3))" }}
                />
              </svg>
              <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center" }}>
                <span style={{ fontSize: 30, fontWeight: 700, color: "#fff", textShadow: "0 2px 6px rgba(0,0,0,0.15)" }}>{mins}:{String(secs).padStart(2,"0")}</span>
                <span style={{ fontSize: 11, color: "rgba(255,255,255,0.5)" }}>of 45:00</span>
              </div>
            </div>
          </div>
          {/* Pill */}
          <div style={{ display: "flex", justifyContent: "center", marginBottom: 14 }}>
            <SessionPill progress={isBreak ? progress : 100 - progress} />
          </div>
          {/* Status */}
          <div style={{ textAlign: "center", marginBottom: 14 }}>
            <p style={{ fontSize: 15, fontWeight: 600, color: "#fff", margin: 0, animation: "pulse-text 4s ease-in-out infinite" }}>{STATUS[msgIdx]}</p>
            <p style={{ fontSize: 12, color: "rgba(255,255,255,0.45)", margin: "5px 0 0 0" }}>
              {isBreak
                ? `Replacing with: ${TOPICS.filter(t => unaddictTopics.includes(t.id)).map(t => t.name).join(" & ")}`
                : TOPICS.filter(t => topics.includes(t.id)).map(t => t.name).join(" & ")
              }
            </p>
            {beforeScore !== null && (
              <p style={{ fontSize: 11, color: "rgba(255,255,255,0.35)", margin: "3px 0 0 0" }}>
                Starting at {Math.round(beforeScore * 100)}% match
              </p>
            )}
          </div>
          {/* Live log */}
          <div style={{ padding: "10px 12px", background: "rgba(0,0,0,0.2)", borderRadius: 12, marginBottom: 14, backdropFilter: "blur(8px)", minHeight: 52 }}>
            {log.slice(-3).map((line, i) => (
              <p key={i} style={{ fontSize: 10, color: "rgba(255,255,255,0.45)", margin: "2px 0", fontFamily: "monospace", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{line}</p>
            ))}
            {log.length === 0 && <p style={{ fontSize: 11, color: "rgba(255,255,255,0.3)", margin: 0 }}>Starting session...</p>}
          </div>
          <button onClick={() => { window.lytesnap?.stopSession(); onStop(); }} style={{
            width: "100%", padding: "12px",
            background: "rgba(255,255,255,0.15)", backdropFilter: "blur(8px)",
            color: "rgba(255,255,255,0.5)", border: "none", borderRadius: 14,
            fontSize: 13, fontWeight: 600, cursor: "pointer",
          }}>Stop session</button>
        </div>
      </div>
    </div>
  );
};

// ─── Results ──────────────────────────────────────────────────────────────────
const ResultsScreen = ({ topics, unaddictTopics = [], phase, beforeScore, onCompound, onSwitchMode, onDone, onNav }) => {
  const [afterScore, setAfterScore] = useState(null);
  const [revealed, setRevealed] = useState(false);
  const [compoundHover, setCompoundHover] = useState(false);
  const [switchHover, setSwitchHover] = useState(false);
  const isBreak = phase === "unaddict";
  const activeTopics = isBreak ? unaddictTopics : topics;
  const names = TOPICS.filter(t => activeTopics.includes(t.id)).map(t => t.name).join(" & ");
  const scoringTopic = activeTopics.filter(id => TOPIC_MAP[id]).map(id => TOPIC_MAP[id].main).join(' or ');

  useEffect(() => {
    window.lytesnap?.scoreFeed(scoringTopic).then(r => {
      setAfterScore(r?.weighted_score ?? 0);
      setTimeout(() => setRevealed(true), 400);
    });
  }, []);

  const beforePct = Math.round((beforeScore ?? 0) * 100);
  const afterPct = afterScore !== null ? Math.round(afterScore * 100) : null;
  const delta = afterPct !== null ? afterPct - beforePct : null;

  return (
    <div style={{ position: "relative", minHeight: 820 }}>
      <SunriseBg phase={isBreak ? "dawn" : "complete"} />
      <div style={{ position: "relative", zIndex: 1 }}>
        <NavBar screen="results" onNav={onNav} />
        <div style={{ padding: "0 20px 24px", textAlign: "center" }}>
          <div style={{ fontSize: 48, marginBottom: 8, animation: "sun-breathe 3s ease-in-out infinite" }}>
            {isBreak ? "🌅" : "🌞"}
          </div>
          <h2 style={{ fontSize: 24, fontWeight: 700, color: "#fff", margin: "0 0 4px 0" }}>
            {isBreak ? "Unaddicted." : "A new day."}
          </h2>
          <p style={{ fontSize: 14, color: "rgba(255,255,255,0.65)", margin: "0 0 20px 0" }}>
            {isBreak ? `${names} now dominates the feed.` : "The feed has been rebuilt."}
          </p>
          {/* Scores */}
          <div style={{ display: "flex", gap: 12, marginBottom: 14 }}>
            <div style={{ flex: 1, padding: "18px 14px", background: "rgba(255,255,255,0.92)", borderRadius: 20, textAlign: "center" }}>
              <div style={{ fontSize: 10, fontWeight: 700, color: "#999", letterSpacing: 1, marginBottom: 6 }}>BEFORE</div>
              <div style={{ fontSize: 34, fontWeight: 700, color: "#636e72" }}>{beforePct}%</div>
            </div>
            <div style={{ flex: 1, padding: "18px 14px", background: "rgba(255,255,255,0.92)", borderRadius: 20, textAlign: "center", opacity: revealed ? 1 : 0, transform: revealed ? "translateY(0)" : "translateY(12px)", transition: "all 0.7s" }}>
              <div style={{ fontSize: 10, fontWeight: 700, color: "#4CAF50", letterSpacing: 1, marginBottom: 6 }}>AFTER</div>
              <div style={{ fontSize: 34, fontWeight: 700, color: "#4CAF50" }}>
                {afterPct !== null ? `${afterPct}%` : "…"}
              </div>
            </div>
          </div>
          {delta !== null && revealed && (
            <div style={{ padding: "12px 16px", background: "rgba(255,255,255,0.85)", borderRadius: 14, marginBottom: 20, transition: "opacity 0.7s ease 0.3s" }}>
              <span style={{ fontSize: 14, fontWeight: 700, color: delta >= 0 ? "#4CAF50" : "#E85D75" }}>
                {delta >= 0 ? `+${delta}%` : `${delta}%`} {names} in the feed
              </span>
            </div>
          )}
          {/* Compound */}
          <button onClick={onCompound}
            onMouseEnter={() => setCompoundHover(true)} onMouseLeave={() => setCompoundHover(false)}
            style={{
              width: "100%", padding: "16px", marginBottom: 10,
              background: compoundHover ? "linear-gradient(135deg, #E85D75, #C94058)" : "rgba(255,255,255,0.2)",
              color: compoundHover ? "#fff" : "rgba(255,255,255,0.7)",
              border: "none", borderRadius: 18, fontSize: 15, fontWeight: 700, cursor: "pointer",
              transition: "all 0.35s",
              boxShadow: compoundHover ? "0 4px 15px rgba(232,93,117,0.35)" : "none",
              transform: compoundHover ? "translateY(-2px)" : "none",
            }}>{isBreak ? "Compound — unaddict again ↑" : "Compound — enjoy again ↑"}</button>
          {/* Switch */}
          <button onClick={onSwitchMode}
            onMouseEnter={() => setSwitchHover(true)} onMouseLeave={() => setSwitchHover(false)}
            style={{
              width: "100%", padding: "14px", marginBottom: 10,
              background: switchHover
                ? (isBreak ? "linear-gradient(135deg, #5C9CE6, #3A7BD5)" : "linear-gradient(135deg, #E85D75, #C94058)")
                : "rgba(255,255,255,0.2)",
              color: switchHover ? "#fff" : "rgba(255,255,255,0.7)",
              border: "none", borderRadius: 14, fontSize: 14, fontWeight: 600, cursor: "pointer",
              transition: "all 0.35s", backdropFilter: "blur(8px)",
            }}>{isBreak ? "Switch to Enjoy →" : "Switch to Unaddict →"}</button>
          <button onClick={onDone} style={{ background: "none", border: "none", cursor: "pointer", fontSize: 13, color: "rgba(255,255,255,0.35)", paddingTop: 4 }}>Done</button>
        </div>
      </div>
    </div>
  );
};

// ─── Schedule ─────────────────────────────────────────────────────────────────
const ScheduleScreen = ({ onNav, scheduleOn, setScheduleOn }) => {
  const [saved, setSaved] = useState(false);
  const [schedStatus, setSchedStatus] = useState(null);
  const [countdown, setCountdown] = useState('');

  useEffect(() => {
    if (!schedStatus?.nextRunTime) { setCountdown(''); return; }
    const update = () => {
      const diff = new Date(schedStatus.nextRunTime) - Date.now();
      if (diff <= 0) { setCountdown('now'); return; }
      const h = Math.floor(diff / 3600000);
      const m = Math.floor((diff % 3600000) / 60000);
      setCountdown(h > 0 ? `${h}h ${m}m` : `${m}m`);
    };
    update();
    const t = setInterval(update, 30000);
    return () => clearInterval(t);
  }, [schedStatus?.nextRunTime]);

  useEffect(() => {
    window.lytesnap?.getScheduleStatus().then(setSchedStatus);
    window.lytesnap?.onScheduleStatusChanged(setSchedStatus);
    return () => window.lytesnap?.removeAllListeners('schedule-status-changed');
  }, []);

  const [confirmReset, setConfirmReset] = useState(false);

  const save = () => {
    window.lytesnap?.setSchedule({ enabled: scheduleOn }).then(() => {
      window.lytesnap?.getScheduleStatus().then(setSchedStatus);
    });
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  const resetSchedule = () => {
    if (!confirmReset) { setConfirmReset(true); setTimeout(() => setConfirmReset(false), 3000); return; }
    setConfirmReset(false);
    window.lytesnap?.resetSchedule().then(setSchedStatus);
  };

  const phaseLabel = () => {
    if (!schedStatus || schedStatus.phase === 'inactive') return "Not started";
    if (schedStatus.phase === 'complete') return "Treatment complete";
    const day = (schedStatus.daysElapsed ?? 0) + 1;
    return schedStatus.phase === 'intensive'
      ? `Day ${day} — Intensive (every 3 hrs)`
      : `Day ${day} — Maintenance (once/day)`;
  };

  const lastRunLabel = () => {
    if (!schedStatus?.lastRunTime) return null;
    const d = new Date(schedStatus.lastRunTime);
    return `Last run: ${d.toLocaleDateString()} ${d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`;
  };

  return (
    <div style={{ position: "relative", minHeight: 820, background: "linear-gradient(180deg, #2D1B69 0%, #6B3FA0 25%, #C85C8E 50%, #F4845F 75%, #F7B267 100%)" }}>
      <div style={{ position: "relative", zIndex: 1 }}>
        <NavBar screen="schedule" onNav={onNav} />
        <div style={{ padding: "0 20px 28px" }}>
          <h2 style={{ fontSize: 22, fontWeight: 700, color: "#fff", margin: "0 0 4px 0" }}>Schedule</h2>
          <p style={{ fontSize: 13, color: "rgba(255,255,255,0.5)", margin: "0 0 16px 0" }}>Automate the treatment. We work while they sleep.</p>
          {/* Toggle */}
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "16px 18px", background: "rgba(255,255,255,0.92)", borderRadius: 18, marginBottom: 12 }}>
            <div>
              <div style={{ fontSize: 15, fontWeight: 600, color: "#2D3436" }}>Run automatically</div>
              <div style={{ fontSize: 12, color: "#bbb", marginTop: 2 }}>{scheduleOn ? "Running every ~3 hours" : "Currently off"}</div>
            </div>
            <button onClick={() => setScheduleOn(!scheduleOn)} style={{ width: 48, height: 28, borderRadius: 14, border: "none", cursor: "pointer", background: scheduleOn ? "linear-gradient(135deg, #F4845F, #F7B267)" : "#E0E0E0", position: "relative", transition: "background 0.3s" }}>
              <div style={{ width: 22, height: 22, borderRadius: 11, background: "#fff", position: "absolute", top: 3, left: scheduleOn ? 23 : 3, transition: "left 0.3s", boxShadow: "0 1px 3px rgba(0,0,0,0.15)" }} />
            </button>
          </div>
          {/* Phase status card */}
          <div style={{ padding: "16px 18px", background: "rgba(255,255,255,0.92)", borderRadius: 18, marginBottom: 12 }}>
            <div style={{ fontSize: 14, fontWeight: 600, color: "#2D3436", marginBottom: 4 }}>
              {phaseLabel()}
            </div>
            {lastRunLabel() && (
              <div style={{ fontSize: 12, color: "#999", marginBottom: 6 }}>{lastRunLabel()}</div>
            )}
            {schedStatus?.active && schedStatus.phase === 'intensive' && countdown && (
              <div style={{ fontSize: 12, color: "#555", marginBottom: 6, fontWeight: 500 }}>
                Next session in {countdown}
              </div>
            )}
            <p style={{ fontSize: 12, color: "#aaa", margin: 0, lineHeight: 1.6 }}>
              Days 1–3: every 3 hrs · Days 4–7: once/day · Day 8+: stops automatically.
              Each session starts with a random 1–5 min delay.
            </p>
          </div>
          <button onClick={save} style={{ width: "100%", padding: "15px", background: "linear-gradient(135deg, #F4845F, #F7B267)", color: "#fff", border: "none", borderRadius: 16, fontSize: 15, fontWeight: 700, cursor: "pointer", boxShadow: "0 4px 15px rgba(244,132,95,0.35)", marginBottom: 10 }}>
            {saved ? "Saved ✓" : "Save schedule"}
          </button>
          <button onClick={resetSchedule} style={{ width: "100%", padding: "13px", background: "rgba(255,255,255,0.15)", color: confirmReset ? "#FF6B6B" : "rgba(255,255,255,0.75)", border: `1px solid ${confirmReset ? "#FF6B6B" : "rgba(255,255,255,0.25)"}`, borderRadius: 16, fontSize: 14, fontWeight: 600, cursor: "pointer" }}>
            {confirmReset ? "Tap again to confirm reset" : "Reset to Day 1"}
          </button>
        </div>
      </div>
    </div>
  );
};

// ─── Scroll Indicator ─────────────────────────────────────────────────────────
const ScrollIndicator = ({ containerRef, show }) => {
  const [hasMore, setHasMore] = useState(false);
  useEffect(() => {
    const el = containerRef.current;
    if (!el || !show) { setHasMore(false); return; }
    const check = () => setHasMore(el.scrollHeight - el.scrollTop - el.clientHeight > 50);
    check();
    el.addEventListener("scroll", check);
    return () => el.removeEventListener("scroll", check);
  }, [containerRef, show]);
  if (!show || !hasMore) return null;
  return (
    <div style={{ position: "absolute", bottom: 12, left: "50%", transform: "translateX(-50%)", zIndex: 20, display: "flex", flexDirection: "column", alignItems: "center", animation: "bounce-arrow 1.5s ease-in-out infinite", pointerEvents: "none" }}>
      <div style={{ width: 32, height: 32, borderRadius: "50%", background: "rgba(255,255,255,0.25)", backdropFilter: "blur(8px)", display: "flex", alignItems: "center", justifyContent: "center", boxShadow: "0 2px 8px rgba(0,0,0,0.1)" }}>
        <svg width="14" height="8" viewBox="0 0 14 8" fill="none">
          <path d="M1 1L7 7L13 1" stroke="#fff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </div>
    </div>
  );
};

// ─── App ──────────────────────────────────────────────────────────────────────
const TOPIC_ID_MIGRATIONS = { kdrama: "drama", kpop: null, beauty: "makeup" };

function loadPrefs() {
  try {
    const raw = localStorage.getItem("lytesnap_prefs");
    const prefs = raw ? JSON.parse(raw) : {};
    const migrate = arr => [...new Set(
      (arr ?? [])
        .map(id => id in TOPIC_ID_MIGRATIONS ? TOPIC_ID_MIGRATIONS[id] : id)
        .filter(Boolean)
    )];
    prefs.unaddictTopics = migrate(prefs.unaddictTopics ?? prefs.selected);
    prefs.enjoyTopics = migrate(prefs.enjoyTopics ?? []);
    return prefs;
  } catch { return {}; }
}

export default function App() {
  const prefs = loadPrefs();
  const [screen, setScreen] = useState("setup");
  const [unaddictTopics, setUnaddictTopics] = useState(prefs.unaddictTopics ?? []);
  const [enjoyTopics, setEnjoyTopics] = useState(prefs.enjoyTopics ?? []);
  const [topicsMode, setTopicsMode] = useState('unaddict');
  const [phase, setPhase] = useState(prefs.phase ?? null);
  const [scheduleOn, setScheduleOn] = useState(false);
  const [beforeScore, setBeforeScore] = useState(0);
  const [lastResult, setLastResult] = useState(null);
  const [scheduledStartTime, setScheduledStartTime] = useState(null);
  const scrollRef = useRef(null);

  useEffect(() => {
    localStorage.setItem("lytesnap_prefs", JSON.stringify({ unaddictTopics, enjoyTopics, phase }));
  }, [unaddictTopics, enjoyTopics, phase]);

  useEffect(() => {
    window.lytesnap?.onScheduledSessionStarted(({ startTime }) => {
      setScheduledStartTime(startTime);
      setPhase('unaddict');
      setScreen('session');
    });
    return () => window.lytesnap?.removeAllListeners('scheduled-session-started');
  }, []);

  const toggleUnaddict = id => setUnaddictTopics(s => s.includes(id) ? s.filter(x => x !== id) : s.length < 3 ? [...s, id] : s);
  const toggleEnjoy = id => setEnjoyTopics(s => s.includes(id) ? s.filter(x => x !== id) : s.length < 3 ? [...s, id] : s);
  const goToTopics = mode => { setTopicsMode(mode); setScreen("topics"); };
  const nav = s => setScreen(s);

  const startSession = () => { setScheduledStartTime(null); setScreen("session"); };

  const handleSessionComplete = () => { setScheduledStartTime(null); setScreen("results"); };

  const handleCompound = () => setScreen("session");

  const handleSwitchMode = () => {
    setPhase(phase === "unaddict" ? "enjoy" : "unaddict");
    setScreen("session");
  };

  return (
    <div style={{ width: "100%", height: "100vh", overflow: "hidden", fontFamily: "'DM Sans', sans-serif", position: "relative" }}>
      <div ref={scrollRef} style={{ height: "100%", overflowY: screen === "schedule" ? "auto" : "hidden", overflowX: "hidden", background: "#1B1464" }}>
        {screen === "setup"   && <SetupScreen onComplete={() => setScreen(unaddictTopics.length > 0 && phase ? "home" : "topics")} onSignIn={() => setScreen("auth")} hasPrefs={unaddictTopics.length > 0 && !!phase} />}
        {screen === "topics"  && <TreatmentScreen mode={topicsMode} selected={topicsMode === 'unaddict' ? unaddictTopics : enjoyTopics} onToggle={topicsMode === 'unaddict' ? toggleUnaddict : toggleEnjoy} onStart={() => setScreen(topicsMode === 'unaddict' ? "phase" : "home")} onNav={nav} />}
        {screen === "phase"   && <PhaseScreen topics={unaddictTopics} onChoose={p => { setPhase(p); if (p === 'enjoy' && enjoyTopics.length === 0) { setTopicsMode('enjoy'); setScreen('topics'); } else { setScreen('home'); } }} onNav={nav} />}
        {screen === "home"    && <HomeScreen topics={phase === 'enjoy' ? enjoyTopics : unaddictTopics} phase={phase} lastResult={lastResult} onRun={startSession} onChangeTopics={() => goToTopics(phase === 'enjoy' ? 'enjoy' : 'unaddict')} onChangePhase={() => setScreen("phase")} onSwitchAccount={() => { window.lytesnap?.signOut(); setScreen("auth"); }} onNav={nav} />}
        {screen === "auth"    && <AuthScreen onComplete={() => setScreen("home")} />}
        {screen === "session" && <SessionScreen topics={enjoyTopics} unaddictTopics={unaddictTopics} phase={phase} scheduledStartTime={scheduledStartTime} onBeforeScore={setBeforeScore} onStop={() => { setScheduledStartTime(null); setScreen("home"); }} onComplete={handleSessionComplete} />}
        {screen === "results" && <ResultsScreen topics={enjoyTopics} unaddictTopics={unaddictTopics} phase={phase} beforeScore={beforeScore} onCompound={handleCompound} onSwitchMode={handleSwitchMode} onDone={() => { setLastResult(null); setScreen("home"); }} onNav={nav} />}
        {screen === "schedule" && <ScheduleScreen onNav={nav} scheduleOn={scheduleOn} setScheduleOn={setScheduleOn} />}
      </div>
      <ScrollIndicator containerRef={scrollRef} show={screen === "schedule" && scheduleOn} />
      <style>{`
        @keyframes pulse-text { 0%,100% { opacity: 0.7; } 50% { opacity: 1; } }
        @keyframes pill-spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
        @keyframes sun-breathe { 0%,100% { transform: scale(1); } 50% { transform: scale(1.06); } }
        @keyframes shadow-breathe { 0%,100% { transform: scaleX(1); opacity: 0.4; } 50% { transform: scaleX(0.75); opacity: 0.25; } }
        @keyframes twinkle { 0% { opacity: 0.2; transform: scale(1); } 100% { opacity: 0.8; transform: scale(1.3); } }
        @keyframes bounce-arrow { 0%,100% { transform: translateX(-50%) translateY(0); } 50% { transform: translateX(-50%) translateY(-6px); } }
        @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500;600;700&display=swap');
      `}</style>
    </div>
  );
}
