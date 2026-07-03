/** @odoo-module **/

import { Component, useState, onWillUnmount } from "@odoo/owl";
import { Dropdown } from "@web/core/dropdown/dropdown";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

export class InsightSystrayItem extends Component {
    static components = { Dropdown, DropdownItem };
    static props = [];
    static template = "insight_project.InsightSystrayItem";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.busService = this.env.services.bus_service;
        this.busService.subscribe("insight_project.session_updated", (data) => this._applyData(data));
        this.state = useState({
            status: "break",
            projectId: false,
            projectName: "",
            taskId: false,
            taskName: "",
            isCriticalPath: false,
            startDatetime: false,
            allocatedHours: 0,
            remainingHours: 0,
            elapsed: "00:00:00",
            timeColorClass: "o_insight_time-neutral",
            taskDescription: "",
            tasks: [],
        });
        this._loadState();
        this._timer = setInterval(() => this._tick(), 1000);
        onWillUnmount(() => clearInterval(this._timer));
    }

    async _loadState() {
        const data = await this.orm.call("insight.user.session", "get_systray_state", []);
        this._applyData(data);
    }

    _applyData(data) {
        this.state.status = data.state;
        this.state.projectId = data.project_id;
        this.state.projectName = data.project_name || _t("Sin proyecto");
        this.state.taskId = data.task_id;
        this.state.taskName = data.task_name || _t("Sin tarea");
        this.state.isCriticalPath = data.is_critical_path;
        this.state.startDatetime = data.start_datetime;
        this.state.allocatedHours = data.allocated_hours || 0;
        this.state.remainingHours = data.remaining_hours || 0;
        this.state.taskDescription = data.task_description || "";
        this.state.tasks = data.tasks || [];
    }

    _tick() {
        if (this.state.status !== "active" || !this.state.startDatetime) {
            this.state.elapsed = "00:00:00";
            this.state.timeColorClass = "o_insight_time-neutral";
            return;
        }
        const start = new Date(this.state.startDatetime.replace(" ", "T") + "Z");
        const liveSeconds = Math.max(0, Math.floor((Date.now() - start.getTime()) / 1000));
        if (!this.state.allocatedHours) {
            // Sin horas asignadas todavía (tarea sin planificar) no hay
            // presupuesto contra el cual descontar: mostramos el viejo
            // cronómetro ascendente, sin color de alerta.
            this.state.elapsed = this._formatDuration(liveSeconds);
            this.state.timeColorClass = "o_insight_time-neutral";
            return;
        }
        const allocatedSeconds = this.state.allocatedHours * 3600;
        const remainingSeconds = this.state.remainingHours * 3600 - liveSeconds;
        this.state.elapsed = this._formatDuration(remainingSeconds);
        this.state.timeColorClass = this._colorClass(remainingSeconds, allocatedSeconds);
    }

    _formatDuration(seconds) {
        const sign = seconds < 0 ? "+" : "";
        const abs = Math.abs(Math.round(seconds));
        const h = String(Math.floor(abs / 3600)).padStart(2, "0");
        const m = String(Math.floor((abs % 3600) / 60)).padStart(2, "0");
        const s = String(abs % 60).padStart(2, "0");
        return `${sign}${h}:${m}:${s}`;
    }

    _colorClass(remainingSeconds, allocatedSeconds) {
        if (remainingSeconds < 0) {
            return "o_insight_time-overtime";
        }
        const ratio = allocatedSeconds > 0 ? remainingSeconds / allocatedSeconds : 0;
        if (ratio >= 0.5) {
            return "o_insight_time-ok";
        }
        if (ratio >= 0.15) {
            return "o_insight_time-warning";
        }
        return "o_insight_time-critical";
    }

    onSelectTask(taskId) {
        // El wizard postea la nota de cierre/inicio y llama a switch_task en el
        // backend; este último ya notifica por bus, así que no hace falta
        // refrescar el estado acá.
        this._openSwitchWizard({ default_mode: "switch", default_target_task_id: taskId });
    }

    onNewTask() {
        this._openSwitchWizard({ default_mode: "switch" });
    }

    onTakeBreak() {
        this._openSwitchWizard({ default_mode: "break" });
    }

    _openSwitchWizard(context) {
        this.action.doAction(
            "insight_project.action_insight_session_switch_wizard",
            { additionalContext: context }
        );
    }

    onOpenTask() {
        if (!this.state.taskId) {
            return;
        }
        window.open(`/web#id=${this.state.taskId}&model=project.task&view_type=form`, "_blank");
    }
}

export const systrayInsightItem = {
    Component: InsightSystrayItem,
};

registry
    .category("systray")
    .add("insight_project.InsightSystrayItem", systrayInsightItem, { sequence: 20 });
