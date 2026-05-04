document.addEventListener("DOMContentLoaded", () => {
    const canvas = document.getElementById("canvas-ruleta");
    const ctx = canvas.getContext("2d");
    const btnGirar = document.getElementById("btn-girar");
    const modalPremio = document.getElementById("modal-premio");
    const textoPremio = document.getElementById("texto-premio");
    const formulario = document.getElementById("formulario-datos");
    const btnCerrarModal = document.getElementById("btn-cerrar-modal");
    const imgPremio = document.getElementById("img-premio");

    let premios = [];
    let gradosActuales = 0;
    let premioGanado = null;

    // --- MAGIA MULTIMARCA: LEER COLORES DEL HTML ---
    let divColores = document.getElementById('colores-marca');
    // Si no encuentra el div, usa azul y blanco por defecto. Si lo encuentra, usa el color 1 y el color 2 (o blanco).
    let colorPrimario = divColores ? divColores.getAttribute('data-color1') : "#005CAB";
    let colorSecundario = divColores ? divColores.getAttribute('data-color2') : "#ffffff";
    
    // El arreglo de colores intercala el primario y el secundario
    const coloresGajos = [colorPrimario, colorSecundario];
    const coloresConfeti = [colorPrimario, colorSecundario, '#ffffff'];

    fetch(`/api/premios/${ESTACION_ID}`)
        .then(res => res.json())
        .then(data => {
            premios = data;
            dibujarRuleta();
        });

    function dibujarRuleta() {
        const porcion = 2 * Math.PI / premios.length;
        const centro = canvas.width / 2;

        for (let i = 0; i < premios.length; i++) {
            ctx.beginPath();
            ctx.moveTo(centro, centro);
            ctx.arc(centro, centro, centro, i * porcion, (i + 1) * porcion);
            // Pinta intercalando los colores corporativos
            ctx.fillStyle = coloresGajos[i % 2];
            ctx.fill();
            // Pinta la línea separadora con el color primario
            ctx.strokeStyle = colorPrimario;
            ctx.stroke();

            ctx.save();
            ctx.translate(centro, centro);
            ctx.rotate(i * porcion + porcion / 2);
            ctx.textAlign = "right";
            
            // Si el fondo es oscuro (índice 0, color primario), el texto es blanco. 
            // Si el fondo es claro (índice 1, color secundario), el texto es del color primario.
            ctx.fillStyle = (i % 2 === 0) ? "#ffffff" : colorPrimario; 
            ctx.font = "bold 14px Arial";
            
            let texto = premios[i].nombre.substring(0, 15);
            ctx.fillText(texto, centro - 30, 5); 
            ctx.restore();
        }
    }

    btnGirar.addEventListener("click", () => {
        btnGirar.disabled = true;

        fetch(`/girar/${ESTACION_ID}`, { method: 'POST' })
            .then(res => {
                // Validación para atrapar errores de servidor antes de leer el JSON
                if (!res.ok) throw new Error("Fallo en la respuesta del servidor");
                return res.json();
            })
            .then(premio => {
                premioGanado = premio;
                
                // 1. Buscamos qué porción es la ganadora
                const indicePremio = premios.findIndex(p => p.nombre === premio.nombre);
                
                // 2. Calculamos los grados por porción
                const gradosPorPorcion = 360 / premios.length;
                
                // 3. Ubicamos el centro geométrico de esa porción
                const centroPorcion = (indicePremio * gradosPorPorcion) + (gradosPorPorcion / 2);
                
                // 4. Calculamos cuánto girar para que ese centro quede arriba (270 grados en Canvas)
                let rotacionObjetivo = 270 - centroPorcion;
                
                // 5. Calculamos las vueltas completas previas para no "desenroscar" la ruleta
                const vueltasPrevias = Math.floor(gradosActuales / 360);
                const vueltasNuevas = 5; // Siempre da 5 vueltas de suspenso
                
                // 6. Variación aleatoria para que no caiga SIEMPRE en el centro exacto de la rebanada (más realista)
                const variacionEje = (Math.random() * (gradosPorPorcion * 0.6)) - (gradosPorPorcion * 0.3);

                // Rotación Final
                gradosActuales = rotacionObjetivo + ((vueltasPrevias + vueltasNuevas) * 360) + variacionEje;
                
                // Aplicamos el giro al CSS
                canvas.style.transform = `rotate(${gradosActuales}deg)`;

                setTimeout(() => {
                    modalPremio.classList.remove("oculto");

                    // Mostrar Imagen si existe
                    if (premio.imagen_url && premio.imagen_url.trim() !== "") {
                        imgPremio.src = premio.imagen_url;
                        imgPremio.style.display = "block";
                    } else {
                        imgPremio.style.display = "none";
                    }

                    // --- BLOQUE TRY...CATCH PARA EVITAR QUE SE CONGELE EL TEXTO ---
                    try {
                        if (premio.sector === "NINGUNO") {
                            textoPremio.innerHTML = `<strong>${premio.nombre}</strong><br><span style="font-size:16px;">¡Suerte para la próxima!</span>`;
                            formulario.classList.add("oculto");
                            btnCerrarModal.classList.remove("oculto");
                        } else {
                            textoPremio.innerHTML = `¡Ganaste:<br><strong style="color:${colorPrimario};">${premio.nombre}</strong>!`;
                            formulario.classList.remove("oculto");
                            btnCerrarModal.classList.add("oculto");

                            // Verificamos si la librería de confeti cargó correctamente
                            if (typeof confetti === "function") {
                                var duration = 4000;
                                var end = Date.now() + duration;
                                
                                let divColores = document.getElementById('colores-marca');
                                let colorConfeti = divColores ? [divColores.getAttribute('data-color1'), '#ffffff'] : ['#F1C40F', '#005CAB', '#ffffff'];
                                
                                (function frame() {
                                  confetti({
                                    particleCount: 5, angle: 60, spread: 55, origin: { x: 0 },
                                    colors: colorConfeti, zIndex: 90, disableForReducedMotion: true
                                  });
                                  confetti({
                                    particleCount: 5, angle: 120, spread: 55, origin: { x: 1 },
                                    colors: colorConfeti, zIndex: 90
                                  });
                                  if (Date.now() < end) requestAnimationFrame(frame);
                                }());
                            } else {
                                console.warn("Animación de confeti omitida (librería no cargada).");
                            }
                        }
                    } catch (err) {
                        console.error("Error al mostrar el cartel de premio:", err);
                        textoPremio.innerHTML = `<strong>${premio.nombre}</strong>`;
                        formulario.classList.remove("oculto");
                        btnCerrarModal.classList.add("oculto");
                    }

                }, 5000); 
            })
            .catch(error => {
                console.error("Error al comunicarse con el servidor:", error);
                alert("Hubo un error de conexión al girar la ruleta. Por favor, revisa tu internet y vuelve a intentarlo.");
                btnGirar.disabled = false;
            });
    });

    formulario.addEventListener("submit", (e) => {
        e.preventDefault();
        const btnSubmit = formulario.querySelector("button[type='submit']");
        btnSubmit.disabled = true;
        btnSubmit.innerText = "⏳ Procesando..."; // Le avisamos al usuario que estamos trabajando

        const datos = {
            nombre: document.getElementById("nombre").value,
            dni: document.getElementById("dni").value,
            email: document.getElementById("email").value,
            telefono: document.getElementById("telefono").value,
            premio: premioGanado.nombre,
            sector: premioGanado.sector
        };

        fetch(`/registrar/${ESTACION_ID}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(datos)
        }).then(() => {
            // Reemplazamos todo el formulario por un mensaje elegante en pantalla
            formulario.innerHTML = `
                <div style="background: #eafaf1; padding: 20px; border-radius: 8px; border: 1px solid #27ae60; margin-top: 15px;">
                    <h3 style="color: #27ae60; margin-top: 0; margin-bottom: 10px;">¡Datos guardados con éxito! ✅</h3>
                    <p style="font-size: 15px; color: #333; margin-bottom: 20px;">
                        Revisa tu correo electrónico <strong>(y la carpeta de SPAM)</strong>. Ahí te enviamos tu código de canje.
                    </p>
                    <button onclick="window.location.reload()" class="btn-primario" style="width: 100%; font-size: 16px; padding: 12px;">Finalizar y Girar de Nuevo</button>
                </div>
            `;
        }).catch(() => {
            // Por si se cae el internet justo en ese momento
            btnSubmit.disabled = false;
            btnSubmit.innerText = "Reclamar Premio";
            textoPremio.innerHTML += `<br><span style="color:red; font-size:14px;">Error de conexión. Intenta de nuevo.</span>`;
        });
    });

    btnCerrarModal.addEventListener("click", () => window.location.reload());
});
