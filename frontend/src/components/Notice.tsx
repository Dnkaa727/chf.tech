import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { classes } from "./classes";

export interface NoticeProps {
	text: string;
	tone?: "info" | "error";
}
export function Notice(props: NoticeProps) {
	const { text, tone = "info" } = props;

	return (
		<div className={classes("notice", `notice--${tone}`)} role="status">
			<FontAwesomeIcon
				icon={tone === "error" ? "triangle-exclamation" : "circle-info"}
			/>
			<span>{text}</span>
		</div>
	);
}
