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
            elapsed: "00:00:00",
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
        this.state.taskDescription = data.task_description || "";
        this.state.tasks = data.tasks || [];
    }

    _tick() {
        if (this.state.status !== "active" || !this.state.startDatetime) {
            this.state.elapsed = "00:00:00";
            return;
        }
        const start = new Date(this.state.startDatetime.replace(" ", "T") + "Z");
        const seconds = Math.max(0, Math.floor((Date.now() - start.getTime()) / 1000));
        const h = String(Math.floor(seconds / 3600)).padStart(2, "0");
        const m = String(Math.floor((seconds % 3600) / 60)).padStart(2, "0");
        const s = String(seconds % 60).padStart(2, "0");
        this.state.elapsed = `${h}:${m}:${s}`;
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
