import { useId } from "react";
import { Button } from "../../components";
import type { useInterviewerSpeech } from "../../hooks/useInterviewerSpeech";

type Voice = ReturnType<typeof useInterviewerSpeech>;

function LeopardPortrait({ speaking }: { speaking: boolean }) {
	const id = useId().replace(/:/g, "");
	const spots = [
		[147, 149, 12],
		[171, 126, 10],
		[211, 120, 9],
		[253, 126, 10],
		[281, 149, 12],
		[125, 186, 9],
		[301, 186, 9],
		[122, 215, 8],
		[304, 215, 8],
		[144, 241, 9],
		[280, 241, 9],
		[162, 156, 5],
		[265, 156, 5],
	];
	return (
		<svg
			className={`leopard${speaking ? " leopard--speaking" : ""}`}
			viewBox="0 0 430 450"
			role="img"
			aria-label="Снежный барс в синем костюме и галстуке"
		>
			<defs>
				<linearGradient id={`${id}-suit`} x2="0.8" y2="1">
					<stop stopColor="#253d62" />
					<stop offset="1" stopColor="#132441" />
				</linearGradient>
				<linearGradient id={`${id}-fur`} x2="0.6" y2="1">
					<stop stopColor="#faf8ee" />
					<stop offset="1" stopColor="#becbd2" />
				</linearGradient>
			</defs>
			<ellipse
				cx="215"
				cy="420"
				rx="155"
				ry="16"
				fill="#1c3657"
				opacity=".10"
			/>
			<path
				d="M307 378 Q399 407 390 328 Q385 289 367 311"
				fill="none"
				stroke="#aabcc8"
				strokeWidth="27"
				strokeLinecap="round"
			/>
			<path
				d="M384 358l13 4m-21 22 10 9m-28-1 1 13m20-91 14-2"
				stroke="#62788b"
				strokeWidth="8"
				strokeLinecap="round"
			/>
			<path
				d="M139 280 Q77 293 67 350 L55 414 Q215 443 375 414 L363 350 Q353 293 291 280Z"
				fill={`url(#${id}-suit)`}
			/>
			<path d="M175 275h80l-6 127h-69Z" fill="#fffdf6" />
			<path
				d="M183 280l32 31-24 20-24-44m80-7-32 31 24 20 24-44"
				fill="#e1e9ec"
				stroke="#c9d5df"
				strokeWidth="2"
			/>
			<path
				d="M203 314h24l-5 22 13 58-20 20-20-20 13-58Z"
				fill="#e8ad5e"
			/>
			<path
				d="M159 282l-27 47 29 10-15 21 49 58-22-137m98 1 27 47-29 10 15 21-49 58 22-137"
				fill="#355272"
				stroke="#617b96"
				strokeWidth="2"
			/>
			<path
				d="M296 362h34m-32 0 2-20 11 8 13-9 3 21"
				fill="#d8e8e9"
				stroke="#d8e8e9"
				strokeWidth="3"
			/>
			<circle cx="215" cy="423" r="4" fill="#728aa1" />
			<g className="leopard__head">
				<path
					d="M126 147Q77 101 100 69Q127 49 162 100m142 47q49-46 26-78-27-20-62 31"
					fill={`url(#${id}-fur)`}
					stroke="#728797"
					strokeWidth="3"
				/>
				<path
					d="M124 119Q99 94 113 84q14-7 31 23m162 12q25-25 11-35-14-7-31 23"
					fill="#dbaea6"
				/>
				<path
					d="M113 177Q112 91 215 90Q318 91 317 177l8 27-13 2 8 26-17-1q-13 60-88 64-75-4-88-64l-17 1 8-26-13-2Z"
					fill={`url(#${id}-fur)`}
					stroke="#728797"
					strokeWidth="3"
					strokeLinejoin="round"
				/>
				{spots.map(([cx, cy, size], i) => (
					<path
						key={i}
						d={`M${cx - size / 2} ${cy - size / 2}q${size} ${-size / 2} ${size} ${size / 2}t${-size} ${size / 2}Z`}
						fill="none"
						stroke="#60778a"
						strokeWidth="4"
						opacity=".72"
					/>
				))}
				<path
					d="M151 174q18-11 35-3m58 0q17-8 35 3"
					fill="none"
					stroke="#435b6c"
					strokeWidth="5"
					strokeLinecap="round"
				/>
				<g className="leopard__eyes">
					<ellipse cx="170" cy="194" rx="20" ry="17" fill="#fffefa" />
					<ellipse cx="260" cy="194" rx="20" ry="17" fill="#fffefa" />
					{[173, 257].map((cx) => (
						<g key={cx}>
							<ellipse
								cx={cx}
								cy="195"
								rx="11"
								ry="14"
								fill="#71a8a0"
							/>
							<ellipse
								cx={cx}
								cy="195"
								rx="5"
								ry="11"
								fill="#213b49"
							/>
							<circle cx={cx - 3} cy="190" r="3" fill="white" />
						</g>
					))}
				</g>
				<path
					d="M164 224q-19 10-9 29 19 23 60 24 41-1 60-24 10-19-9-29-19-10-51 0-32-10-51 0"
					fill="#fffdf5"
				/>
				<path
					d="M201 219q14-6 28 0l-14 13Z"
					fill="#485363"
					stroke="#485363"
					strokeWidth="5"
					strokeLinejoin="round"
				/>
				<g className="leopard__mouth" transform="translate(215 249)">
					<ellipse
						className="leopard__mouth-open"
						rx="15"
						ry="10"
						fill="#493947"
					/>
					<ellipse
						className="leopard__tongue"
						cy="5"
						rx="8"
						ry="3"
						fill="#db8e8d"
					/>
				</g>
				<path
					d="M215 231v10m0 0q-10 12-22 4m22-4q10 12 22 4"
					fill="none"
					stroke="#485363"
					strokeWidth="3"
					strokeLinecap="round"
				/>
				<path
					d="M171 235l-43-8m44 18-48 2m134-12 43-8m-44 18 48 2"
					fill="none"
					stroke="#748694"
					strokeWidth="2"
					strokeLinecap="round"
				/>
				<g fill="#82939d">
					<circle cx="179" cy="230" r="2" />
					<circle cx="184" cy="240" r="2" />
					<circle cx="251" cy="230" r="2" />
					<circle cx="246" cy="240" r="2" />
				</g>
			</g>
		</svg>
	);
}

export function SnowLeopard({
	voice,
	thinking,
}: {
	voice: Voice;
	thinking: boolean;
}) {
	const status = voice.speaking
		? "Говорю"
		: voice.busy
			? "Готовлюсь озвучить"
			: thinking
				? "Обдумываю твой ответ"
				: "Жду твой ответ";
	return (
		<div className="mascot-stage">
			<div className="mascot-stage__portrait">
				<div className="mascot-stage__halo" aria-hidden="true" />
				<LeopardPortrait speaking={voice.speaking} />
				<div className="mascot-stage__status" role="status">
					<span className={voice.speaking ? "is-speaking" : ""} />
					{status}
				</div>
			</div>
			<div className="mascot-stage__voice">
				<div className="mascot-stage__buttons">
					<Button
						variant={voice.enabled ? "tonal" : "primary"}
						iconLeft={
							voice.enabled ? "volume-xmark" : "volume-high"
						}
						disabled={
							!voice.supported ||
							(!voice.available && !voice.enabled)
						}
						onClick={voice.enabled ? voice.stop : voice.enable}
					>
						{voice.enabled ? "Выключить голос" : "Включить голос"}
					</Button>
					<Button
						variant="secondary"
						iconLeft="rotate-right"
						disabled={
							!voice.supported || !voice.available || voice.busy
						}
						onClick={voice.repeat}
					>
						Повторить
					</Button>
				</div>
				<p
					className="mascot-stage__hint"
					role={voice.error ? "alert" : "status"}
				>
					{voice.error ??
						(!voice.supported
							? "В этом браузере нет озвучивания. Все реплики доступны в чате."
							: !voice.available
								? "Озвучивание пока недоступно. Можно продолжить в чате."
								: voice.enabled
									? "Вопросы и обратная связь звучат голосом Silero"
									: "Включи голос - я прочитаю вопрос вслух")}
				</p>
			</div>
		</div>
	);
}
