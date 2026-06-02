const { useEffect, useMemo, useRef, useState } = React;

const CONFIG = window.RULETA_CONFIG;

const THEME_ALIASES = {
    YPF_CLASICO: "YPF_RUTA",
    YPF_MODERNO: "YPF_RUTA",
    YPF_LED: "YPF_FULL",
    AXION_CLASICO: "AXION_BOXES",
    AXION_MODERNO: "AXION_BOXES",
    AXION_LED: "AXION_NOCHE"
};

const WHEEL_THEMES = {
    YPF_RUTA: {
        label: "Casino Neon",
        brand: "#00d4ff",
        accent: "#ffe600",
        deep: "#16002f",
        glow: "#ff2bd6",
        slices: ["#ff2bd6", "#00d4ff", "#ffe600", "#34ff6d", "#ff5a1f", "#7c3aed", "#ff1744", "#00ffa8"],
        sticker: "★"
    },
    YPF_FULL: {
        label: "Carnaval Pop",
        brand: "#ff2bd6",
        accent: "#34ff6d",
        deep: "#101042",
        glow: "#00d4ff",
        slices: ["#ff2bd6", "#34ff6d", "#ffe600", "#00d4ff", "#ff7a00", "#9d4edd", "#ff1744", "#ffffff"],
        sticker: "◆"
    },
    AXION_BOXES: {
        label: "Arcade Turbo",
        brand: "#7c3aed",
        accent: "#ff1744",
        deep: "#090018",
        glow: "#ffe600",
        slices: ["#7c3aed", "#ff1744", "#00d4ff", "#ffe600", "#34ff6d", "#ff7a00", "#ffffff", "#00ffa8"],
        sticker: "✦"
    },
    AXION_NOCHE: {
        label: "Jackpot Galaxy",
        brand: "#ffe600",
        accent: "#00ffa8",
        deep: "#05010d",
        glow: "#ff2bd6",
        slices: ["#05010d", "#ff2bd6", "#00ffa8", "#ffe600", "#00d4ff", "#ff1744", "#7c3aed", "#ffffff"],
        sticker: "✹"
    }
};

const themeKey = THEME_ALIASES[CONFIG.estiloRuleta] || CONFIG.estiloRuleta || "YPF_RUTA";
const theme = WHEEL_THEMES[themeKey] || WHEEL_THEMES.YPF_RUTA;
const palette = theme.slices;
const bulbColors = ["#ff3131", "#f4cf22", "#00d4ff", "#22c55e", "#ffffff", "#a855f7", "#fb7185", "#f97316"];

document.documentElement.style.setProperty("--brand", theme.brand);
document.documentElement.style.setProperty("--accent", theme.accent);
document.documentElement.style.setProperty("--deep", theme.deep);
document.documentElement.style.setProperty("--glow", theme.glow);

let audioContext = null;

function playTone(frequency, duration = 0.06, type = "triangle", volume = 0.05) {
    try {
        audioContext = audioContext || new (window.AudioContext || window.webkitAudioContext)();
        const oscillator = audioContext.createOscillator();
        const gain = audioContext.createGain();
        oscillator.type = type;
        oscillator.frequency.setValueAtTime(frequency, audioContext.currentTime);
        gain.gain.setValueAtTime(volume, audioContext.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.001, audioContext.currentTime + duration);
        oscillator.connect(gain);
        gain.connect(audioContext.destination);
        oscillator.start();
        oscillator.stop(audioContext.currentTime + duration);
    } catch (_) {}
}

function emojiSticker(text, index = 0) {
    const found = String(text || "").match(/[\u{1F300}-\u{1FAFF}]/u);
    if (found) return found[0];
    const fallback = ["🎁", "⭐", "💎", "🔥", "🎊", "🏆", "⚡", "🪄"];
    return fallback[index % fallback.length];
}

function drawWheel(canvas, prizes) {
    const ctx = canvas.getContext("2d");
    const size = canvas.width;
    const center = size / 2;
    const radius = center - 42;
    const slice = (Math.PI * 2) / prizes.length;

    ctx.clearRect(0, 0, size, size);

    const outer = ctx.createRadialGradient(center, center, radius * 0.18, center, center, center);
    outer.addColorStop(0, "#ffffff");
    outer.addColorStop(0.42, theme.brand);
    outer.addColorStop(0.72, theme.glow);
    outer.addColorStop(1, theme.deep);
    ctx.beginPath();
    ctx.arc(center, center, center - 8, 0, Math.PI * 2);
    ctx.fillStyle = outer;
    ctx.fill();

    ctx.beginPath();
    ctx.arc(center, center, radius + 28, 0, Math.PI * 2);
    ctx.lineWidth = 24;
    ctx.strokeStyle = theme.accent;
    ctx.stroke();

    for (let i = 0; i < 56; i++) {
        const angle = (Math.PI * 2 / 56) * i;
        const lampX = center + Math.cos(angle) * (radius + 28);
        const lampY = center + Math.sin(angle) * (radius + 28);
        const lampColor = bulbColors[i % bulbColors.length];
        ctx.beginPath();
        ctx.arc(lampX, lampY, i % 2 ? 5 : 8, 0, Math.PI * 2);
        ctx.fillStyle = lampColor;
        ctx.shadowColor = lampColor;
        ctx.shadowBlur = 18;
        ctx.fill();
    }
    ctx.shadowBlur = 0;

    prizes.forEach((prize, index) => {
        const start = index * slice - Math.PI / 2;
        const end = start + slice;
        const color = palette[index % palette.length];
        const darkText = ["#ffffff", "#f4cf22", "#f7e27a", "#ffb4b8", "#facc15", "#fb7185"].includes(color);

        ctx.beginPath();
        ctx.moveTo(center, center);
        ctx.arc(center, center, radius, start, end);
        ctx.closePath();
        ctx.fillStyle = color;
        ctx.fill();
        ctx.lineWidth = 5;
        ctx.strokeStyle = "#ffffff";
        ctx.stroke();

        ctx.save();
        ctx.translate(center, center);
        ctx.rotate(start + slice / 2);
        ctx.textAlign = "right";
        ctx.fillStyle = darkText ? theme.deep : "#ffffff";
        ctx.font = "900 28px Arial";
        ctx.shadowColor = "rgba(0, 0, 0, 0.32)";
        ctx.shadowBlur = darkText ? 0 : 7;
        ctx.fillText(prize.nombre.slice(0, 17), radius - 42, 11);
        ctx.restore();

        ctx.save();
        ctx.translate(center, center);
        ctx.rotate(start + slice / 2);
        ctx.textAlign = "center";
        ctx.font = "42px Arial";
        ctx.shadowColor = theme.glow;
        ctx.shadowBlur = 16;
        ctx.fillText(emojiSticker(prize.nombre, index), radius * 0.46, -16);
        ctx.restore();
    });

    ctx.shadowBlur = 0;
    ctx.beginPath();
    ctx.arc(center, center, radius * 0.28, 0, Math.PI * 2);
    ctx.fillStyle = "#ffffff";
    ctx.fill();
    ctx.lineWidth = 9;
    ctx.strokeStyle = theme.accent;
    ctx.stroke();

    ctx.save();
    ctx.globalAlpha = 0.2;
    ctx.fillStyle = "#ffffff";
    ctx.beginPath();
    ctx.ellipse(center - radius * 0.16, center - radius * 0.35, radius * 0.72, radius * 0.18, -0.3, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
}

function normalizePrizes(prizes) {
    if (!Array.isArray(prizes) || prizes.length === 0) {
        return [{ nombre: "Sigue intentando", imagen_url: "" }, { nombre: "Gira de nuevo", imagen_url: "" }];
    }
    return prizes;
}

function App() {
    const canvasRef = useRef(null);
    const [prizes, setPrizes] = useState([]);
    const [loading, setLoading] = useState(true);
    const [spinning, setSpinning] = useState(false);
    const [degrees, setDegrees] = useState(0);
    const [winner, setWinner] = useState(null);
    const [formSent, setFormSent] = useState(false);
    const [error, setError] = useState("");
    const [winnerReveal, setWinnerReveal] = useState(false);

    const visiblePrizes = useMemo(() => normalizePrizes(prizes), [prizes]);

    useEffect(() => {
        fetch(`/api/premios/${CONFIG.estacionId}`)
            .then((res) => {
                if (!res.ok) throw new Error("No se pudieron cargar los premios.");
                return res.json();
            })
            .then((data) => setPrizes(normalizePrizes(data)))
            .catch(() => setError("No se pudieron cargar los premios de esta estacion."))
            .finally(() => setLoading(false));
    }, []);

    useEffect(() => {
        if (canvasRef.current && visiblePrizes.length > 0) {
            drawWheel(canvasRef.current, visiblePrizes);
        }
    }, [visiblePrizes]);

    function spin() {
        setSpinning(true);
        setWinner(null);
        setWinnerReveal(false);
        setFormSent(false);
        setError("");
        playTone(160, 0.16, "sawtooth", 0.035);

        let tickCount = 0;
        const tickTimer = setInterval(() => {
            tickCount += 1;
            playTone(420 + (tickCount % 7) * 38, 0.035, "square", 0.025);
            if (tickCount > 62) clearInterval(tickTimer);
        }, 72);

        fetch(`/girar/${CONFIG.estacionId}`, { method: "POST" })
            .then((res) => {
                if (!res.ok) throw new Error("No se pudo girar.");
                return res.json();
            })
            .then((premio) => {
                const index = visiblePrizes.findIndex((item) => item.nombre === premio.nombre);
                const safeIndex = index >= 0 ? index : 0;
                const sliceDegrees = 360 / visiblePrizes.length;
                const center = safeIndex * sliceDegrees + sliceDegrees / 2;
                const target = 270 - center;
                const jitter = (Math.random() * sliceDegrees * 0.56) - (sliceDegrees * 0.28);
                const nextDegrees = (Math.floor(degrees / 360) + 7) * 360 + target + jitter;

                setDegrees(nextDegrees);
                setTimeout(() => {
                    setWinner(premio);
                    setWinnerReveal(true);
                    setSpinning(false);
                    playTone(523, 0.16, "triangle", 0.06);
                    setTimeout(() => playTone(659, 0.18, "triangle", 0.055), 110);
                    setTimeout(() => playTone(880, 0.24, "triangle", 0.05), 230);
                    if (premio.sector !== "NINGUNO" && typeof confetti === "function") {
                        confetti({ particleCount: 180, spread: 88, origin: { y: 0.65 }, colors: palette });
                        setTimeout(() => confetti({ particleCount: 90, angle: 60, spread: 70, origin: { x: 0, y: 0.75 }, colors: bulbColors }), 220);
                        setTimeout(() => confetti({ particleCount: 90, angle: 120, spread: 70, origin: { x: 1, y: 0.75 }, colors: bulbColors }), 320);
                    }
                }, 4900);
            })
            .catch(() => {
                clearInterval(tickTimer);
                setError("Hubo un error de conexion al girar la ruleta.");
                setSpinning(false);
            });
    }

    function submitClaim(event) {
        event.preventDefault();
        const form = new FormData(event.currentTarget);
        const payload = {
            nombre: form.get("nombre"),
            dni: form.get("dni"),
            email: form.get("email"),
            telefono: form.get("telefono"),
            premio: winner.nombre,
            sector: winner.sector
        };

        fetch(`/registrar/${CONFIG.estacionId}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        })
            .then((res) => {
                if (!res.ok) throw new Error("No se pudo registrar.");
                return res.json();
            })
            .then(() => setFormSent(true))
            .catch(() => setError("No se pudieron guardar los datos. Intenta de nuevo."));
    }

    return (
        <main className={`react-shell theme-${themeKey} ${spinning ? "is-spinning" : ""} ${winnerReveal ? "winner-reveal" : ""}`}>
            <div className="casino-particles" aria-hidden="true">
                {Array.from({ length: 26 }).map((_, index) => <span key={index} style={{ "--p": index }}></span>)}
            </div>
            <section className="stage">
                <div className="brand-title">
                    <span className="casino-kicker">Jackpot station</span>
                    <h1>{CONFIG.nombreEstacion}</h1>
                    <p>{theme.label}: gira, brilla y descubri tu premio.</p>
                </div>

                <div className="wheel-card">
                    <div className="wheel-glow"></div>
                    <div className="wheel-shine"></div>
                    <div className="bulb-ring" aria-hidden="true">
                        {Array.from({ length: 32 }).map((_, index) => (
                            <span
                                key={index}
                                style={{
                                    "--bulb-index": index,
                                    "--bulb-color": bulbColors[index % bulbColors.length]
                                }}
                            ></span>
                        ))}
                    </div>
                    <div className="wheel-pointer"></div>
                    <canvas
                        ref={canvasRef}
                        className="react-wheel"
                        width="900"
                        height="900"
                        style={{ transform: `rotate(${degrees}deg)` }}
                    ></canvas>
                    <div className="wheel-hub">{theme.center || (themeKey.includes("AXION") ? "AX" : "YPF")}</div>
                </div>

                <button className="spin-button" onClick={spin} disabled={loading || spinning}>
                    <span>{spinning ? "Girando..." : "Girar"}</span>
                </button>
                {error && <p className="error">{error}</p>}
            </section>

            {winner && (
                <div className="modal-backdrop">
                    <div className="win-burst" aria-hidden="true"></div>
                    <div className="result-modal">
                        <h2>🎉 ¡GANASTE! 🎉</h2>
                        <div className="winner-sticker">{emojiSticker(winner.nombre)}</div>
                        {winner.imagen_url && <img src={winner.imagen_url} alt={winner.nombre} />}
                        <p className="result-name">{winner.nombre}</p>

                        {winner.sector === "NINGUNO" ? (
                            <>
                                <p>Gracias por participar. Podes volver a intentarlo en tu proxima carga.</p>
                                <button className="modal-action" onClick={() => window.location.reload()}>Finalizar</button>
                            </>
                        ) : formSent ? (
                            <div className="success-box">
                                Datos guardados. Revisa el correo electronico y la carpeta de spam para ver el codigo de canje.
                            </div>
                        ) : (
                            <form className="claim-form" onSubmit={submitClaim}>
                                <input name="nombre" type="text" placeholder="Nombre y Apellido" required />
                                <input name="dni" type="number" placeholder="DNI" required />
                                <input name="email" type="email" placeholder="Correo Electronico" required />
                                <input name="telefono" type="tel" placeholder="Telefono" required />
                                <button type="submit">Reclamar premio</button>
                            </form>
                        )}
                    </div>
                </div>
            )}
        </main>
    );
}

ReactDOM.createRoot(document.getElementById("ruleta-react-root")).render(<App />);
