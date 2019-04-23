# -*- coding: utf-8 -*-
# See LICENSE file for full copyright and licensing details.

import time
from datetime import datetime, date, timedelta
from odoo import models, fields, _, api
from odoo.tools import misc, DEFAULT_SERVER_DATE_FORMAT
from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT
from odoo.tools.float_utils import float_compare
from odoo.exceptions import Warning, ValidationError


class ServiceCategory(models.Model):
    _name = 'service.category'

    name = fields.Char(string="Service Category", size=2, translate=True)

    @api.multi
    def copy(self, default=None):
        raise Warning(_('You can\'t duplicate record!'))

    @api.multi
    def unlink(self):
        raise Warning(_('You can\'t delete record !'))


class FleetVehicleLogServices(models.Model):
    _inherit = 'fleet.vehicle.log.services'
    _order = 'id desc'

    @api.multi
    def copy(self, default=None):
        raise Warning(_('You can\'t duplicate record!'))

    @api.multi
    def unlink(self):
        for rec in self:
            if rec.state != 'draft':
                raise Warning(_('You can\'t delete Work Order which \
                                  in Confirmed or Done state!'))
        return super(FleetVehicleLogServices, self).unlink()

    @api.onchange('vehicle_id')
    def get_vehicle_info(self):
        if self.vehicle_id:
            vehicle = self.vehicle_id
            self.vechical_type_id = vehicle.vechical_type_id and \
                vehicle.vechical_type_id.id or False,
            self.purchaser_id = vehicle.driver_id and \
                vehicle.driver_id.id or False,
            self.fmp_id = vehicle.name or "",
            self.f_brand_id = vehicle.f_brand_id and \
                vehicle.f_brand_id.id or False,
            self.vehical_division_id = vehicle.vehical_division_id and \
                vehicle.vehical_division_id.id or False,
            self.vechical_location_id = vehicle.vechical_location_id and \
                vehicle.vechical_location_id.id or False,

    @api.multi
    def action_confirm(self):
        sequence = self.env['ir.sequence'].next_by_code('work.order.sequence')
        mod_obj = self.env['ir.model.data']
        cr, uid, context = self.env.args
        context = dict(context)
        for work_order in self:
            if work_order.vehicle_id:
                if work_order.vehicle_id.state == 'write-off':
                    raise Warning(_("You can\'t confirm this \
                            work order which vehicle is in write-off state!"))
                elif work_order.vehicle_id.state == 'in_progress':
                    raise Warning(_("Previous work order is not \
                            complete, complete that work order first than \
                                you can confirm this work order!"))
                elif work_order.vehicle_id.state == 'draft' or \
                        work_order.vehicle_id.state == 'complete':
                    raise Warning(_("Confirm work order can only \
                        when vehicle status is in Inspection or Released!"))
                work_order.vehicle_id.write({
                    'state': 'in_progress',
                    'last_change_status_date': date.today(),
                    'work_order_close': False})
            work_order.write({'state': 'confirm', 'name': sequence,
                              'date_open':
                              time.strftime(DEFAULT_SERVER_DATE_FORMAT)})
            model_data_ids = mod_obj.search([
                ('model', '=', 'ir.ui.view'),
                ('name', '=', 'continue_pending_repair_form_view')])
            resource_id = model_data_ids.read(['res_id'])[0]['res_id']
            context.update({'work_order_id': work_order.id,
                            'vehicle_id': work_order.vehicle_id and
                            work_order.vehicle_id.id or False})
            self.env.args = cr, uid, misc.frozendict(context)
            if work_order.vehicle_id:
                for pending_repair in \
                        work_order.vehicle_id.pending_repair_type_ids:
                    if pending_repair.state == 'in-complete':
                        return {
                            'name': _('Previous Repair Types'),
                            'context': self._context,
                            'view_type': 'form',
                            'view_mode': 'form',
                            'res_model': 'continue.pending.repair',
                            'views': [(resource_id, 'form')],
                            'type': 'ir.actions.act_window',
                            'target': 'new',
                        }
        return True

    @api.multi
    def action_done(self):
        cr, uid, context = self.env.args
        context = dict(context)
        odometer_increment = 0.0
        increment_obj = self.env['next.increment.number']
        next_service_day_obj = self.env['next.service.days']
        mod_obj = self.env['ir.model.data']

        for work_order in self:
            for repair_line in work_order.repair_line_ids:
                if repair_line.complete is True:
                    continue
                elif repair_line.complete is False:
                    model_data_ids = mod_obj.search([
                        ('model', '=', 'ir.ui.view'),
                        ('name', '=', 'pending_repair_confirm_form_view')])
                    resource_id = model_data_ids.read(['res_id'])[0]['res_id']
                    context.update({'work_order_id': work_order.id})
                    self.env.args = cr, uid, misc.frozendict(context)
                    return {
                        'name': _('WO Close Forcefully'),
                        'context': context,
                        'view_type': 'form',
                        'view_mode': 'form',
                        'res_model': 'pending.repair.confirm',
                        'views': [(resource_id, 'form')],
                        'type': 'ir.actions.act_window',
                        'target': 'new',
                    }
        increment_ids = increment_obj.search([
            ('vehicle_id', '=', work_order.vehicle_id.id)])
        if not increment_ids:
            raise Warning(_("Next Increment \
                    Odometer is not set for %s please set it from \
                    configuration!") % (work_order.vehicle_id.name))
        if increment_ids:
            odometer_increment = increment_ids[0].number
        next_service_day_ids = next_service_day_obj.search([
            ('vehicle_id', '=', work_order.vehicle_id.id)])
        if not next_service_day_ids:
            raise Warning(_("Next service days is \
                     not configured for %s please set it from \
                     configuration!") % (work_order.vehicle_id.name))

        work_order_vals = {}
        for work_order in self:
            self.env.args = cr, uid, misc.frozendict(context)
            if work_order.odometer == 0:
                raise Warning(_("Please set the current \
                                     Odometer of vehilce in work order!"))
            odometer_increment += work_order.odometer
            next_service_date = datetime.strptime(
                str(date.today()), DEFAULT_SERVER_DATE_FORMAT) + \
                timedelta(days=next_service_day_ids[0].days)
            work_order_vals.update({
                'state': 'done',
                'next_service_odometer': odometer_increment,
                'already_closed': True,
                'closed_by': uid,
                'date_close': date.today(),
                'next_service_date': next_service_date})
            work_order.write(work_order_vals)
            if work_order.vehicle_id:
                work_order.vehicle_id.write({
                    'state': 'complete',
                    'last_service_by_id': work_order.team_id and
                    work_order.team_id.id or False,
                    'last_service_date': date.today(),
                    'next_service_date': next_service_date,
                    'due_odometer': odometer_increment,
                    'due_odometer_unit': work_order.odometer_unit,
                    'last_change_status_date': date.today(),
                    'work_order_close': True})
                if work_order.already_closed:
                    for repair_line in work_order.repair_line_ids:
                        for pending_repair_line in \
                                work_order.vehicle_id.pending_repair_type_ids:
                            if repair_line.repair_type_id.id == \
                                pending_repair_line.repair_type_id.id and \
                                    work_order.name == \
                                    pending_repair_line.name:
                                if repair_line.complete is True:
                                    pending_repair_line.unlink()
            if work_order.parts_ids:
                parts = self.env['task.line'].search([
                    ('fleet_service_id', '=', work_order.id),
                    ('is_deliver', '=', False)])
                if parts:
                    for part in parts:
                        part.write({'is_deliver': True})
                        source_location = self.env.ref(
                            'stock.picking_type_out').default_location_src_id
                        dest_location, loc = self.env[
                            'stock.warehouse']._get_partner_locations()
                        move = self.env['stock.move'].create({
                            'name': 'Use on Work Order',
                            'product_id': part.product_id.id or False,
                            'location_id': source_location.id,
                            'location_dest_id': dest_location.id,
                            'product_uom': part.product_uom.id or False,
                            'product_uom_qty': part.qty or 0.0
                        })
                        move.action_confirm()
                        move.action_assign()
                        move.action_done()
        return True

    @api.multi
    def encode_history(self):
        """Method is used to create the Encode Qty
        History for Team Trip from WO."""

        wo_part_his_obj = self.env['workorder.parts.history.details']
        if self._context.get('team_trip', False):
            team_trip = self._context.get('team_trip', False)
            work_order = self._context.get('workorder', False)
            # If existing parts Updated
            wo_part_his_ids = wo_part_his_obj.search([
                ('team_id', '=', team_trip and team_trip.id or False),
                ('wo_id', '=', work_order and work_order.id or False)])
            if wo_part_his_ids:
                wo_part_his_ids.unlink()
            wo_part_dict = {}
            for part in work_order.parts_ids:
                wo_part_dict[part.product_id.id] = \
                    {'wo_en_qty': part.encoded_qty, 'qty': part.qty}
            for t_part in team_trip.allocate_part_ids:
                if t_part.product_id.id in wo_part_dict.keys():
                    new_wo_encode_qty = \
                        wo_part_dict[t_part.product_id.id]['wo_en_qty'] - \
                        wo_part_dict[t_part.product_id.id]['qty']
                    wo_part_history_vals = {
                        'team_id': team_trip.id,
                        'product_id': t_part.product_id.id,
                        'name': t_part.product_id.name,
                        'vehicle_make': t_part.product_id.vehicle_make_id.id,
                        'used_qty': wo_part_dict[t_part.product_id.id]['qty'],
                        'wo_encoded_qty':
                        wo_part_dict[t_part.product_id.id]['wo_en_qty'],
                        'new_encode_qty': new_wo_encode_qty,
                        'wo_id': work_order.id,
                        'used_date': t_part.issue_date,
                        'issued_by': self._uid or False
                    }
                    wo_part_his_obj.create(wo_part_history_vals)
                    t_part.write({'encode_qty': new_wo_encode_qty})
        return True

    @api.multi
    def action_reopen(self):
        for order in self:
            if order.vehicle_id:
                if order.vehicle_id.state == 'write-off':
                    raise Warning(_("You can\'t Re-open this \
                            work order which vehicle is in write-off state!"))
                elif order.vehicle_id.state == 'in_progress':
                    raise Warning(_("Previous work order is not \
                         complete, complete that work order first than \
                          you can Re-Open work order!"))
                elif order.vehicle_id.state == 'draft' or \
                        order.vehicle_id.state == 'complete':
                    raise Warning(_("Re-open work order can \
                                only be generated either vehicle status \
                                    is in Inspection or Released!"))
                order.vehicle_id.write({'work_order_close': False,
                                        'state': 'in_progress'})
            self.write({'state': 'confirm'})
        return True

    @api.depends('parts_ids')
    def _compute_get_total(self):
        for rec in self:
            total = 0.0
            for line in rec.parts_ids:
                total += line.total
            rec.sub_total = total

    @api.constrains('amount', 'sub_total')
    def _check_amount(self):
        for rec in self:
            if rec.amount:
                if rec.amount < rec.sub_total:
                    raise Warning(
                        _("Total Price should be greater or equals\
                         to total amount of parts!!"))

    @api.multi
    def write(self, vals):
        for work_order in self:
            if work_order.vehicle_id:
                vals.update({
                    'fmp_id': work_order.vehicle_id and
                    work_order.vehicle_id.name or "",
                    'vechical_type_id': work_order.vehicle_id and
                    work_order.vehicle_id.vechical_type_id and
                    work_order.vehicle_id.vechical_type_id.id or False,
                    'purchaser_id': work_order.vehicle_id and
                    work_order.vehicle_id.driver_id and
                    work_order.vehicle_id.driver_id.id or False,
                    'main_type': work_order.vehicle_id.main_type,
                    'f_brand_id': work_order.vehicle_id and
                    work_order.vehicle_id.f_brand_id and
                    work_order.vehicle_id.f_brand_id.id or False,
                    'vehical_division_id': work_order.vehicle_id and
                    work_order.vehicle_id.vehical_division_id and
                    work_order.vehicle_id.vehical_division_id.id or False,
                    'vechical_location_id': work_order.vehicle_id and
                    work_order.vehicle_id.vechical_location_id and
                    work_order.vehicle_id.vechical_location_id.id or False,
                })
        return super(FleetVehicleLogServices, self).write(vals)

    @api.model
    def _get_location(self):
        location_id = self.env['stock.location'].search([
            ('name', '=', 'Vehicle')])
        if location_id:
            return location_id.ids[0]
        return False

    @api.model
    def service_send_mail(self):
        model_obj = self.env['ir.model.data']
        send_obj = self.env['mail.template']
        res = model_obj.get_object_reference('fleet_operations',
                                             'email_template_edi_fleet')
        server_obj = self.env['ir.mail_server']
        record_obj = model_obj.get_object_reference('fleet_operations',
                                                    'ir_mail_server_service')
        self._cr.execute("SELECT id FROM fleet_vehicle WHERE \
                            next_service_date = DATE(NOW()) + 1")
        vehicle_ids = [i[0] for i in self._cr.fetchall() if i]
        email_from_brw = server_obj.browse(record_obj[1])
        if res:
            temp_rec = send_obj.browse(res[1])
        for rec in self.browse(vehicle_ids):
            email_from = email_from_brw.smtp_user
            if not email_from:
                raise Warning(_("May be Out Going Mail \
                                    server is not configuration."))
            if vehicle_ids:
                temp_rec.send_mail(rec.id, force_send=True)
        return True

    @api.model
    def default_get(self, fields):
        vehicle_obj = self.env['fleet.vehicle']
        repair_type_obj = self.env['repair.type']
        if self._context.get('active_ids', False):
            for vehicle in vehicle_obj.browse(self._context['active_ids']):
                if vehicle.state == 'write-off':
                    raise Warning(_("You can\'t create work order \
                             for vehicle which is already write-off!"))
                elif vehicle.state == 'in_progress':
                    raise Warning(_("Previous work order is not \
                        complete, complete that work order first than you \
                        can create new work order!"))
                elif vehicle.state == 'rent':
                    raise Warning(_("You can\'t create work order \
                             for vehicle which is already On Rent!"))
                elif vehicle.state == 'draft' or vehicle.state == 'complete':
                    raise Warning(_("New work order can only be \
                            generated either vehicle status is in \
                            Inspection or Released!"))
        res = super(FleetVehicleLogServices, self).default_get(fields)
        repair_type_ids = repair_type_obj.search([])
        if not repair_type_ids:
            raise Warning(_("There is no data for \
                        repair type, add repair type from configuration!"))
        return res

    @api.onchange('cost_subtype_id')
    def get_repair_line(self):
        repair_lines = []
        if self.cost_subtype_id:
            for repair_type in self.cost_subtype_id.repair_type_ids:
                repair_lines.append((0, 0, {'repair_type_id': repair_type.id}))
            self.repair_line_ids = repair_lines

    @api.multi
    def _get_open_days(self):
        for work_order in self:
            diff = 0
            if work_order.state == 'confirm':
                diff = (datetime.today() -
                        datetime.strptime(work_order.date_open,
                                          DEFAULT_SERVER_DATE_FORMAT)).days
                work_order.open_days = str(diff)
            elif work_order.state == 'done':
                diff = (datetime.strptime(work_order.date_close,
                                          DEFAULT_SERVER_DATE_FORMAT) -
                        datetime.strptime(work_order.date_open,
                                          DEFAULT_SERVER_DATE_FORMAT)).days
                work_order.open_days = str(diff)
            else:
                work_order.open_days = str(diff)

    @api.multi
    def _get_total_parts_line(self):
        for work_order in self:
            total_parts = [parts_line.id
                           for parts_line in work_order.parts_ids
                           if parts_line]
            work_order.total_parts_line = len(total_parts)

    @api.model
    def get_warehouse(self):
        warehouse_ids = self.env['stock.warehouse'].search([])
        if warehouse_ids:
            return warehouse_ids.ids[0]
        else:
            return False

    @api.onchange('vehicle_id')
    def _onchange_vehicle(self):
        if not self.vehicle_id:
            return {}
        if self.vehicle_id:
            self.odometer = self.vehicle_id.odometer
            self.odometer_unit = self.vehicle_id.odometer_unit
            self.purchaser_id = self.vehicle_id.driver_id.id

    @api.constrains('date', 'date_complete')
    def check_complete_date(self):
        for vehicle in self:
            if vehicle.date and vehicle.date_complete:
                if vehicle.date_complete < vehicle.date:
                    raise ValidationError('ETIC Date Should Be \
                    Greater Than Issue Date.')

    wono_id = fields.Integer(string='WONo',
                             help="Take this field for data migration")
    purchaser_id = fields.Many2one('res.partner', string='Purchaser')
    name = fields.Char(string='Work Order', size=32, readonly=True,
                       translate=True)
    fmp_id = fields.Char(string="Vehicle ID", size=64)
    wo_tax_amount = fields.Float(string='Tax', readonly=True)
    priority = fields.Selection([('normal', 'NORMAL'), ('high', 'HIGH'),
                                 ('low', 'LOW')], default='normal',
                                string='Work Priority')
    date_complete = fields.Date(string='Issued Complete ',
                                help='Date when the service is completed')
    date_open = fields.Date(string='Open Date',
                            help="When Work Order \
                                        will confirm this date will be set.")
    date_close = fields.Date(string='Date Close',
                             help="Closing Date of Work Order")
    closed_by = fields.Many2one('res.users', string='Closed By')
    etic = fields.Boolean(string='ETIC', help="Estimated Time In Completion",
                          default=True)
    wrk_location_id = fields.Many2one('stock.location',
                                      string='Location', readonly=True)
    wrk_attach_ids = fields.One2many('ir.attachment', 'wo_attachment_id',
                                     string='Attachments')
    task_ids = fields.One2many('service.task', 'main_id',
                               string='Service Task')
    parts_ids = fields.One2many('task.line', 'fleet_service_id',
                                string='Parts')
    note = fields.Text(string='Notes')
    date_child = fields.Date(related='cost_id.date', string='Date', store=True)
    inv_ref = fields.Many2one('account.invoice', string='Invoice Reference',
                              readonly=True)
    sub_total = fields.Float(compute="_compute_get_total", string='Total Cost',
                             default=0.0, store=True)
    state = fields.Selection([('draft', 'New'),
                              ('confirm', 'Open'), ('done', 'Close'),
                              ('cancel', 'Cancel')], string='Status',
                             default='draft', readonly=True)
    warehouse_id = fields.Many2one('stock.warehouse', string='Warehouse')
    delivery_id = fields.Many2one('stock.picking',
                                  string='Delivery Reference', readonly=True)
    team_id = fields.Many2one('res.partner', string="Teams")
    maintenance_team_id = fields.Many2one("stock.location", string="Teams")
    next_service_date = fields.Date(string='Next Service Date')
    next_service_odometer = fields.Float(string='Next Odometer Value',
                                         readonly=True)
    repair_line_ids = fields.One2many('service.repair.line', 'service_id',
                                      string='Repair Lines')
    old_parts_incoming_ship_ids = fields.One2many('stock.picking',
                                                  'work_order_old_id',
                                                  string='Old Returned',
                                                  readonly=True)
    reopen_return_incoming_ship_ids = fields.One2many('stock.picking',
                                                      'work_order_reopen_id',
                                                      string='Reopen Returned',
                                                      readonly=True)
    out_going_ids = fields.One2many('stock.picking', 'work_order_out_id',
                                    string='Out Going', readonly=True)
    vechical_type_id = fields.Many2one('vehicle.type', string='Vechical Type')
    open_days = fields.Char(compute="_get_open_days", string="Open Days")
    already_closed = fields.Boolean("Already Closed?")
    total_parts_line = fields.Integer(compute="_get_total_parts_line",
                                      string='Total Parts')
    is_parts = fields.Boolean(string="Is Parts Available?")
    from_migration = fields.Boolean('From Migration')
    main_type = fields.Selection([('vehicle', 'Vehicle'),
                                  ('non-vehicle', ' Non-Vehicle')],
                                 string='Main Type')
    f_brand_id = fields.Many2one('fleet.vehicle.model.brand', string='Make')
    vehical_division_id = fields.Many2one('vehicle.divison', string='Division')
    vechical_location_id = fields.Many2one('res.country.state',
                                           string='Registration State')
    odometer = fields.Float(compute='_get_odometer', inverse='_set_odometer',
                            string='Last Odometer',
                            help='Odometer measure of the vehicle at the \
                                moment of this log')

    def _get_odometer(self):
        fleet_odometer_obj = self.env['fleet.vehicle.odometer']
        for record in self:
            vehicle_odometer = fleet_odometer_obj.search([
                ('vehicle_id', '=', record.vehicle_id.id)], limit=1,
                order='value desc')
            if vehicle_odometer:
                record.odometer = vehicle_odometer.value
            else:
                record.odometer = 0

    def _set_odometer(self):
        fleet_odometer_obj = self.env['fleet.vehicle.odometer']
        for record in self:
            vehicle_odometer = fleet_odometer_obj.search(
                [('vehicle_id', '=', record.vehicle_id.id)],
                limit=1, order='value desc')
            if record.odometer < vehicle_odometer.value:
                raise Warning(_('You can\'t enter odometer less than previous \
                               odometer %s !') % (vehicle_odometer.value))
            if record.odometer:
                date = fields.Date.context_today(record)
                data = {'value': record.odometer, 'date': date,
                        'vehicle_id': record.vehicle_id.id}
                fleet_odometer_obj.create(data)


class WorkorderPartsHistoryDetails(models.Model):
    _name = 'workorder.parts.history.details'
    _order = 'used_date desc'

    product_id = fields.Many2one('product.product', string='Part No',
                                 help='The Part Number')
    name = fields.Char(string='Part Name', help='The Part Name',
                       translate=True)
    vehicle_make = fields.Many2one('fleet.vehicle.model.brand',
                                   string='Vehicle Make',
                                   help='The Make of the Vehicle')
    used_qty = fields.Float(string='Encoded Qty',
                            help='The Quantity that is used in in Workorder')
    wo_encoded_qty = fields.Float(string='Qty',
                                  help='The Quantity which is \
                                  available to use')
    new_encode_qty = fields.Float(string='Qty for Encoding',
                                  help='New Encoded Qty')
    wo_id = fields.Many2one('fleet.vehicle.log.services', string='Workorder',
                            help='The workorder for which the part was used')
    used_date = fields.Datetime(string='Issued Date')
    issued_by = fields.Many2one('res.users', string='Issued by',
                                help='The user who would issue the parts')


class TripPartsHistoryDetails(models.Model):
    _name = 'trip.encoded.history'

    @api.multi
    def _get_encoded_qty(self):
        res = {}
        for parts_load in self:
            res[parts_load.id] = 0.0
            total__encode_qty = 0.0
            if parts_load.team_id and parts_load.team_id.wo_parts_ids:
                query = "select sum(used_qty) from \
                            workorder_parts_history_details where \
                            product_id=" + str(parts_load.product_id.id) + \
                    " and team_id=" + str(parts_load.team_id.id)
                self._cr.execute(query)
                result = self._cr.fetchone()
                total__encode_qty = result and result[0] or 0.0
                parts_load.write({'encoded_qty': total__encode_qty})
            if total__encode_qty:
                res[parts_load.id] = total__encode_qty
        return res

    @api.multi
    def _get_available_qty(self):
        for rec in self:
            available_qty = rec.used_qty - rec.dummy_encoded_qty
            if available_qty < 0:
                raise Warning(_('Quantity Available \
                                    must be greater than zero!'))
            rec.available_qty = available_qty

    product_id = fields.Many2one('product.product', string='Part No',
                                 help='The Part Number')
    part_name = fields.Char(string='Part Name', size=128, translate=True)
    used_qty = fields.Float(string='Used Qty',
                            help='The Quantity that is used in in \
                                    Contact Team Trip')
    encoded_qty = fields.Float(string='Encoded Qty',
                               help='The Quantity that is used in \
                                        in Workorder')
    dummy_encoded_qty = fields.Float(compute="_get_encoded_qty",
                                     string='Encoded Qty')
    available_qty = fields.Float(compute="_get_available_qty",
                                 string='Qty for Encoding',
                                 help='The Quantity which is available to use')


class TripPartsHistoryDetailsTemp(models.Model):
    _name = 'trip.encoded.history.temp'

    product_id = fields.Many2one('product.product', string='Part No',
                                 help='The Part Number')
    used_qty = fields.Float(string='Used Qty',
                            help='The Quantity that is used in in Workorder')
    work_order_id = fields.Many2one('fleet.vehicle.log.services',
                                    string="Work Order")


class StockPicking(models.Model):
    _inherit = 'stock.picking'
    _order = 'id desc'

    work_order_out_id = fields.Many2one('fleet.vehicle.log.services',
                                        string="Work Order")
    work_order_old_id = fields.Many2one('fleet.vehicle.log.services',
                                        string="Work Order")
    work_order_reopen_id = fields.Many2one('fleet.vehicle.log.services',
                                           string="Work Order")
    stock_warehouse_id = fields.Many2one('stock.warehouse', string='Warehouse')
    received_by_id = fields.Many2one('res.users', string='Received By')

    @api.model
    def create(self, vals):
        if vals.get('origin', False) and vals['origin'][0] == ':':
            vals.update({'origin': vals['origin'][1:]})
        if vals.get('origin', False) and vals['origin'][-1] == ':':
            vals.update({'origin': vals['origin'][:-1]})
        return super(StockPicking, self).create(vals)

    @api.multi
    def write(self, vals):
        if vals.get('origin', False) and vals['origin'][0] == ':':
            vals.update({'origin': vals['origin'][1:]})
        if vals.get('origin', False) and vals['origin'][-1] == ':':
            vals.update({'origin': vals['origin'][:-1]})
        return super(StockPicking, self).write(vals)

    @api.multi
    def unlink(self):
        raise Warning(_('You can\'t delete record !'))

    @api.multi
    def do_partial_from_migration_script(self):
        assert len(self._ids) == 1, 'Partial picking processing \
                                    may only be done one at a time.'
        stock_move = self.env['stock.move']
        uom_obj = self.env['product.uom']
        partial = self and self[0]
        partial_data = {
            'delivery_date': partial and partial.date or False
        }
        picking_type = ''
        if partial and partial.picking_type_id and \
                partial.picking_type_id.code == 'incoming':
            picking_type = 'in'
        elif partial and partial.picking_type_id and \
                partial.picking_type_id.code == 'outgoing':
            picking_type = 'out'
        elif partial and partial.picking_type_id and \
                partial.picking_type_id.code == 'internal':
            picking_type = 'int'
        for wizard_line in partial.move_lines:
            line_uom = wizard_line.product_uom
            move_id = wizard_line.id

            # Compute the quantity for respective wizard_line in
            # the line uom (this jsut do the rounding if necessary)
            qty_in_line_uom = uom_obj._compute_qty(line_uom.id,
                                                   wizard_line.product_qty,
                                                   line_uom.id)

            if line_uom.factor and line_uom.factor != 0:
                if float_compare(qty_in_line_uom, wizard_line.product_qty,
                                 precision_rounding=line_uom.rounding) != 0:
                    raise Warning(_('The unit of measure \
                            rounding does not allow you to ship "%s %s", \
                            only rounding of "%s %s" is accepted by the \
                            Unit of Measure.') % (wizard_line.product_qty,
                                                  line_uom.name,
                                                  line_uom.rounding,
                                                  line_uom.name))
            if move_id:
                # Check rounding Quantity.ex.
                # picking: 1kg, uom kg rounding = 0.01 (rounding to 10g),
                # partial delivery: 253g
                # => result= refused, as the qty left on picking
                # would be 0.747kg and only 0.75 is accepted by the uom.
                initial_uom = wizard_line.product_uom
                # Compute the quantity for respective
                # wizard_line in the initial uom
                qty_in_initial_uom = \
                    uom_obj._compute_qty(line_uom.id,
                                         wizard_line.product_qty,
                                         initial_uom.id)
                without_rounding_qty = (wizard_line.product_qty /
                                        line_uom.factor) * initial_uom.factor
                if float_compare(qty_in_initial_uom, without_rounding_qty,
                                 precision_rounding=initial_uom.rounding) != 0:
                    raise Warning(_('The rounding of the \
                        initial uom does not allow you to ship "%s %s", \
                        as it would let a quantity of "%s %s" to ship and \
                        only rounding of "%s %s" is accepted \
                        by the uom.') % (wizard_line.product_qty,
                                         line_uom.name,
                                         wizard_line.product_qty -
                                         without_rounding_qty,
                                         initial_uom.name,
                                         initial_uom.rounding,
                                         initial_uom.name))
            else:
                seq_obj_name = 'stock.picking.' + picking_type
                move_id = stock_move.create({
                    'name': self.env['ir.sequence'].next_by_code(
                        seq_obj_name),
                    'product_id': wizard_line.product_id and
                    wizard_line.product_id.id or False,
                    'product_qty': wizard_line.product_qty,
                    'product_uom': wizard_line.product_uom and
                    wizard_line.product_uom.id or False,
                    'prodlot_id': wizard_line.prodlot_id and
                    wizard_line.prodlot_id.id or False,
                    'location_id': wizard_line.location_id and
                    wizard_line.location_id.id or False,
                    'location_dest_id': wizard_line.location_dest_id and
                    wizard_line.location_dest_id.id or False,
                    'picking_id': partial and partial.id or False
                })
                move_id.action_confirm()
            partial_data['move%s' % (move_id.id)] = {
                'product_id': wizard_line.product_id and
                wizard_line.product_id.id or False,
                'product_qty': wizard_line.product_qty,
                'product_uom': wizard_line.product_uom and
                wizard_line.product_uom.id or False,
                'prodlot_id': wizard_line.prodlot_id and
                wizard_line.prodlot_id.id or False,
            }
            product_currency_id = \
                wizard_line.product_id.company_id.currency_id and \
                wizard_line.product_id.company_id.currency_id.id or False
            picking_currency_id = \
                partial.company_id.currency_id and \
                partial.company_id.currency_id.id or False
            if (picking_type == 'in') and \
                    (wizard_line.product_id.cost_method == 'average'):
                partial_data['move%s' % (wizard_line.id)].update(
                    product_price=wizard_line.product_id.standard_price,
                    product_currency=product_currency_id or
                    picking_currency_id or False)
        partial.do_partial(partial_data)
        if partial.purchase_id:
            partial.purchase_id.write({'state': 'done'})
        return True


class StockMove(models.Model):
    _inherit = 'stock.move'
    _order = 'id desc'

    type = fields.Many2one(related='picking_id.picking_type_id',
                           string='Shipping Type',
                           store=True)
    issued_received_by_id = fields.Many2one('res.users', string='Received By')

    @api.onchange('picking_type_id', 'location_id', 'location_dest_id')
    def onchange_move_type(self):
        """On change of move type gives sorce and destination location."""
        if not self.location_id and not self.location_dest_id:
            mod_obj = self.env['ir.model.data']
            location_source_id = 'stock_location_stock'
            location_dest_id = 'stock_location_stock'
            if self.picking_type_id and \
                    self.picking_type_id.code == 'incoming':
                location_source_id = 'stock_location_suppliers'
                location_dest_id = 'stock_location_stock'
            elif self.picking_type_id and \
                    self.picking_type_id.code == 'outgoing':
                location_source_id = 'stock_location_stock'
                location_dest_id = 'stock_location_customers'
            source_location = mod_obj.get_object_reference('stock',
                                                           location_source_id)
            dest_location = mod_obj.get_object_reference('stock',
                                                         location_dest_id)
            self.location_id = source_location and source_location[1] or False
            self.location_dest_id = dest_location and dest_location[1] or False

    @api.model
    def _default_location_source(self):
        location_id = super(StockMove, self)._default_location_source()
        if self._context.get('stock_warehouse_id', False):
            warehouse_pool = self.env['stock.warehouse']
            for rec in warehouse_pool.browse(
                    [self._context['stock_warehouse_id']]):
                if rec.lot_stock_id:
                    location_id = rec.lot_stock_id.id
        return location_id

    @api.model
    def _default_location_destination(self):
        location_dest_id = super(StockMove, self)._default_location_source()
        if self._context.get('stock_warehouse_id', False):
            warehouse_pool = self.env['stock.warehouse']
            for rec in warehouse_pool.browse(
                    [self._context['stock_warehouse_id']]):
                if rec.wh_output_id_stock_loc_id:
                    location_dest_id = rec.wh_output_id_stock_loc_id and \
                        rec.wh_output_id_stock_loc_id.id or False
        return location_dest_id


class TeamAssignParts(models.Model):
    _name = 'team.assign.parts'

    @api.multi
    def _get_remaining_parts(self):
        for parts_load in self:
            used = parts_load.qty_used + \
                parts_load.qty_missing + parts_load.qty_damage
            total = parts_load.qty_with_team + parts_load.qty_on_truck
            parts_load.qty_remaining = total - used

    @api.multi
    def _get_remaining_encode_qty(self):
        for parts_load in self:
            remaining_encode_qty = 0.0
            total__encode_qty = 0.0
            if parts_load.team_id and parts_load.team_id.wo_parts_ids:
                for wo_parts_rec in parts_load.team_id.wo_parts_ids:
                    if parts_load.product_id.id == wo_parts_rec.product_id.id:
                        total__encode_qty += wo_parts_rec.used_qty
                remaining_encode_qty = parts_load.qty_used - total__encode_qty
                parts_load.encode_qty = remaining_encode_qty
            if total__encode_qty:
                parts_load.dummy_encode_qty = remaining_encode_qty
            else:
                parts_load.dummy_encode_qty = parts_load.qty_used

    trip_history_id = fields.Integer(string='Trip Part History ID',
                                     help="Take this field for data migration")
    product_id = fields.Many2one('product.product', string='PartNo',
                                 required=True)
    name = fields.Char(string='Part Name', size=124, translate=True)
    vehicle_make_id = fields.Many2one('fleet.vehicle.model.brand',
                                      string='Vehicle Make')
    encode_qty = fields.Float(string='Encode Qty')
    qty_on_hand = fields.Float(string='Qty on Hand')
    qty_on_truck = fields.Float(string='Qty on Truck', required=True)
    qty_used = fields.Float(string='Used')
    qty_missing = fields.Float(string='Missing')
    qty_damage = fields.Float(string='Damage')
    qty_remaining = fields.Float(compute="_get_remaining_parts",
                                 string='Remaining')
    remark = fields.Char(string='Remark', size=32, translate=True)
    state = fields.Selection([('open', 'Open'), ('sent', 'Sent'),
                              ('returned', 'Returned'),
                              ('close', 'Close')], string='Status',
                             default='open')
    qty_with_team = fields.Float(string='Qty with Team',
                                 help='This will be the quantity in \
                                     case if the parts are kept with the Team')
    to_return = fields.Boolean(string='Return?',
                               help='This will be checked in case we are \
                                       returning the parts back to stock')
    issued_by = fields.Many2one('res.users', string='Issued by',
                                default=lambda self: self._uid,
                                help='The user who would issue the parts')
    issue_date = fields.Date(string='Issue Date',
                             help='The date when the part was issued.')
    is_delete_line = fields.Boolean(string='Delete line?')
    dummy_encode_qty = fields.Float(compute="_get_remaining_encode_qty",
                                    string='Remaining encode qty')

    @api.multi
    def unlink(self):
        for product in self:
            if product.state == 'returned':
                raise Warning('Warning!', 'You can delete parts when contact \
                                            team trip is in return stage !')
            elif product.is_delete_line:
                raise Warning('Warning!', 'You can delete parts when contact \
                                            team trip is already return!')
        return super(TeamAssignParts, self).unlink()

    @api.model
    def create(self, vals):
        product_obj = self.env['product.product']
        if not vals.get('issue_date', False):
            vals.update({'issue_date':
                         time.strftime(DEFAULT_SERVER_DATE_FORMAT)})
        if vals.get('product_id', False):
            prod = product_obj.browse(vals['product_id'])
            vals.update({
                'name': prod.name or "",
                'vehicle_make_id': prod.vehicle_make_id and
                prod.vehicle_make_id.id or False,
                'qty_on_hand': prod.qty_available or 0.0
            })
        if vals.get('team_id', False) and vals.get('product_id', False):
            team_line_ids = self.search([
                ('team_id', '=', vals['team_id']),
                ('product_id', '=', vals['product_id'])])
            if team_line_ids:
                product_rec = product_obj.browse(vals['product_id'])
                raise Warning(_('You can not have duplicate \
                                parts assigned !!! \n Part No :- ' +
                                str(product_rec.default_code)))
        return super(TeamAssignParts, self).create(vals)

    @api.multi
    def write(self, vals):
        if vals.get('product_id', False) or vals.get('qty_on_truck', False):
            vals.update({
                'issued_by': self._uid,
                'issue_date': time.strftime(DEFAULT_SERVER_DATE_FORMAT)})
        return super(TeamAssignParts, self).write(vals)

    @api.onchange('qty_with_team', 'qty_on_truck', 'qty_used',
                  'qty_missing', 'qty_damage')
    def check_used_damage(self):
        total_used = self.qty_used + self.qty_missing + self.qty_damage
        qty_team = self.qty_on_truck + self.qty_with_team
        if total_used > qty_team:
            self.qty_used = 0.0
            self.qty_missing = 0.0
            self.qty_damage = 0.0
            raise Warning('Warning!', 'Total of Used, Missing and \
                           damage can not be greater than qty on truck!')

    @api.onchange('qty_on_hand', 'qty_on_truck')
    def check_used_qty_in_truck(self):
        if self.qty_on_truck > self.qty_on_hand:
            self.qty_on_truck = False
            raise Warning('User Error!!', 'Qty on Truck can not be \
                                greater than qty on hand!')

    @api.multi
    def copy(self, default=None):
        raise Warning(_('You can\'t duplicate record!'))

    @api.onchange('product_id')
    def onchange_product_id(self):
        if self.product_id:
            rec = self.product_id
            if rec.in_active_part:
                self.product_id = False
                self.name = False
                self.vehicle_make_id = False
                self.qty_on_hand = False
                self.qty_on_truck = False
                self.qty_used = 0.0
                self.qty_missing = 0.0
                self.qty_damage = 0.0
                self.qty_remaining = False
                self.remark = False
                self.price_unit = False
                self.date_issued = False
                self.old_part_return = False
                raise Warning(_('You can\'t select \
                                        part which is In-Active!'))
            part_name = rec.name or ''
            if rec.qty_available <= 0:
                self.product_id = False
                self.name = False
                self.vehicle_make_id = False
                self.qty = 0.0
                raise Warning(_('You can\'t select part \
                                    which has zero quantity!'))
            self.name = part_name
            self.vehicle_make_id = rec.vehicle_make_id and \
                rec.vehicle_make_id.id or False,
            self.qty_on_hand = rec.qty_available or 0.0

    @api.onchange('issue_date')
    def onchange_issue_date(self):
        if not self._context:
            self._context = {}
        issue_date_o = self.issue_date or False
        trip_date = False
        return_date = False
        if self._context.get('trip_date', False):
            trip_date = datetime.strptime(self._context['trip_date'],
                                          '%Y-%m-%d').date()
        if self._context.get('return_date', False):
            return_date = datetime.strptime(self._context['return_date'],
                                            '%Y-%m-%d').date()
        if issue_date_o:
            issue_date = datetime.strptime(issue_date_o[:10],
                                           '%Y-%m-%d').date()
            if trip_date and return_date:
                if trip_date > issue_date or issue_date > return_date:
                    self.issue_date = False
                    raise Warning(_('Please enter \
                            issue date between Trip Date and Return Date!'))
            elif trip_date:
                if trip_date > issue_date or issue_date > date.today():
                    self.issue_date = False
                    raise Warning(_('Please enter \
                        issue date between Trip Date and Current Date!'))
            elif return_date:
                if return_date < issue_date or issue_date < date.today():
                    self.issue_date = False
                    raise Warning(_('Please enter \
                            issue date between Current Date and Return Date!'))
            elif not trip_date and not return_date and \
                    issue_date != date.today():
                self.issue_date = False
                raise Warning(_('Please enter current date \
                                           in issue date!!'))
        self.issue_date = issue_date_o


class StockLocation(models.Model):
    _inherit = 'stock.location'

    is_team = fields.Boolean(string='Is Team?')
    workshop = fields.Char(string='Work Shop Name')
    trip = fields.Boolean(string="Trip?")
    is_team_trip = fields.Boolean(tring="Is Team Trip", store=True)

    @api.multi
    def name_get(self):
        res = {}
        for m in self:
            res[m.id] = m.name
        return res.items()


class FleetWorkOrderSearch(models.TransientModel):
    _name = 'fleet.work.order.search'
    _rec_name = 'state'

    priority = fields.Selection([('normal', 'NORMAL'), ('high', 'HIGH'),
                                 ('low', 'LOW')], string='Order Priority')
    state = fields.Selection([('confirm', 'Open'), ('done', 'Close'),
                              ('any', 'Any')], string='Status')
    part_id = fields.Many2one('product.product', string='Parts')
    issue_date_from = fields.Date(string='Issue From')
    issue_date_to = fields.Date(string='Issue To')
    open_date_from = fields.Date(string='Open From')
    open_date_to = fields.Date(string='Open To')
    close_date_form = fields.Date(string='Close From')
    close_date_to = fields.Date(string='Close To')
    vehical_division_id = fields.Many2one('vehicle.divison',
                                          string="Division")
    work_order_id = fields.Many2one('fleet.vehicle.log.services',
                                    string='Work Order No')
    fmp_id = fields.Many2one('fleet.vehicle', string='Vehicle ID')
    cost_subtype_id = fields.Many2one('fleet.service.type',
                                      string='Service Type')
    repair_type_id = fields.Many2one('repair.type', string='Repair Type')
    open_days = fields.Char(string='Open Days', size=16)
    make_id = fields.Many2one("fleet.vehicle.model.brand", string="Make")
    model_id = fields.Many2one("fleet.vehicle.model", string="Model")

    @api.constrains('issue_date_from', 'issue_date_to')
    def check_issue_date(self):
        for vehicle in self:
            if vehicle.issue_date_to:
                if vehicle.issue_date_to < vehicle.issue_date_from:
                    raise ValidationError('Issue To Date Should Be \
                    Greater Than Last Issue From Date.')

    @api.constrains('open_date_from', 'open_date_to')
    def check_open_date(self):
        for vehicle in self:
            if vehicle.open_date_to:
                if vehicle.open_date_to < vehicle.open_date_from:
                    raise ValidationError('Open To Date Should Be \
                    Greater Than Open From Date.')

    @api.constrains('close_date_form', 'close_date_to')
    def check_close_date(self):
        for vehicle in self:
            if vehicle.close_date_to:
                if vehicle.close_date_to < vehicle.close_date_form:
                    raise ValidationError('Close To Date Should Be \
                    Greater Than Close From Date.')

    @api.multi
    def get_work_order_detail_by_advance_search(self):
        vehicle_obj = self.env['fleet.vehicle']
        work_order_obj = self.env['fleet.vehicle.log.services']
        part_line_obj = self.env['task.line']
        repair_line_obj = self.env['service.repair.line']
        domain = []
        order_ids = []
        for order in self:
            if order.make_id:
                vehicle_ids = vehicle_obj.search([
                    ('f_brand_id', '=', order.make_id.id)])
                if vehicle_ids:
                    order_ids = work_order_obj.search([
                        ('vehicle_id', 'in', vehicle_ids.ids)]).ids
                order_ids = sorted(set(order_ids))
            if order.model_id:
                vehicle_ids = vehicle_obj.search([
                    ('model_id', '=', order.model_id.id)])
                if vehicle_ids:
                    order_ids = work_order_obj.search([
                        ('vehicle_id', 'in', vehicle_ids.ids)]).ids
                order_ids = sorted(set(order_ids))
            part_id = order.part_id and order.part_id.id or False
            if part_id:
                parts_line_ids = part_line_obj.search([
                    ('product_id', '=', part_id)])
                if parts_line_ids:
                    for part_line in parts_line_ids:
                        order_ids.append(part_line.fleet_service_id.id)
                    order_ids = sorted(set(order_ids))

            repair_type_id = order.repair_type_id and \
                order.repair_type_id.id or False
            if repair_type_id:
                repair_line_ids = repair_line_obj.search([
                    ('repair_type_id', '=', repair_type_id)])
                if repair_line_ids:
                    for repair_line in repair_line_ids:
                        if repair_line.service_id:
                            order_ids.append(repair_line.service_id.id)
                    order_ids = sorted(set(order_ids))

            fmp_id = order.fmp_id and order.fmp_id.id or False
            if order.open_days:
                wrk_ids = work_order_obj.search([])
                if wrk_ids:
                    for wk_order in wrk_ids:
                        if wk_order.date_open:
                            diff = (datetime.today() -
                                    datetime.strptime(
                                        wk_order.date_open,
                                        DEFAULT_SERVER_DATE_FORMAT)).days
                            if str(diff) == wk_order.open_days:
                                order_ids.append(wk_order.id)
                    order_ids = sorted(set(order_ids))

            if fmp_id:
                work_order_ids = work_order_obj.search([
                    ('vehicle_id', '=', fmp_id)])
                if work_order_ids:
                    for work_line in work_order_ids:
                        order_ids.append(work_line.id)
                    order_ids = sorted(set(order_ids))

            division_id = order.vehical_division_id and \
                order.vehical_division_id.id or False
            if division_id:
                vehicle_ids = vehicle_obj.search([
                    ('vehical_division_id', '=', division_id)])
                work_order_ids = work_order_obj.search([
                    ('vehicle_id', 'in', vehicle_ids.ids)])
                if work_order_ids:
                    for work_line in work_order_ids:
                        order_ids.append(work_line.id)
                    order_ids = sorted(set(order_ids))

            if order.state == 'confirm' or order.state == 'done':
                domain.append(('state', '=', order.state))
            if order.priority:
                domain += [('priority', '=', order.priority)]
            if order.work_order_id:
                order_ids.append(order.work_order_id.id)
            if order.cost_subtype_id:
                domain += [('cost_subtype_id', '=', order.cost_subtype_id.id)]
            if order.issue_date_from and order.issue_date_to:
                domain += [('date', '>=', order.issue_date_from)]
                domain += [('date', '<=', order.issue_date_to)]
            elif order.issue_date_from:
                domain += [('date', '=', order.issue_date_from)]
            if order.open_date_from and order.open_date_to:
                domain += [('date_open', '>=', order.open_date_from)]
                domain += [('date_open', '<=', order.open_date_to)]
            elif order.open_date_from:
                domain += [('date_open', '=', order.open_date_from)]
            if order.close_date_form and order.close_date_to:
                domain += [('date_close', '>=', order.close_date_form)]
                domain += [('date_close', '<=', order.close_date_to)]
            elif order.close_date_form:
                domain += [('date_close', '=', order.close_date_form)]

            if order.part_id or order.work_order_id or order.repair_type_id \
                    or order.fmp_id or order.vehical_division_id or \
                    order.open_days or order.make_id or order.model_id:
                domain += [('id', 'in', order_ids)]

            return {
                'name': _('Work Order'),
                'view_type': 'form',
                "view_mode": 'tree,form',
                'res_model': 'fleet.vehicle.log.services',
                'type': 'ir.actions.act_window',
                'nodestroy': True,
                'domain': domain,
                'context': self._context,
                'target': 'current',
            }
        return True


class ResUsers(models.Model):
    _inherit = 'res.users'

    usersql_id = fields.Char(string='User ID',
                             help="Take this field for data migration")


class IrAttachment(models.Model):
    _inherit = 'ir.attachment'

    wo_attachment_id = fields.Many2one('fleet.vehicle.log.services')


class ServiceTask(models.Model):
    _name = 'service.task'
    _description = 'Maintenance of the Task '

    main_id = fields.Many2one('fleet.vehicle.log.services',
                              string='Maintanace Reference')
    type = fields.Many2one('fleet.service.type', string='Type')
    total_type = fields.Float(string='Cost', readonly=True, default=0.0)
    product_ids = fields.One2many('task.line', 'task_id', string='Product')
    maintenance_info = fields.Text(string='Information', translate=True)


class TaskLine(models.Model):
    _name = 'task.line'

    task_id = fields.Many2one('service.task',
                              string='task reference')
    fleet_service_id = fields.Many2one('fleet.vehicle.log.services',
                                       string='Vehicle Work Order')
    product_id = fields.Many2one('product.product', string='Part',
                                 required=True)
    qty_hand = fields.Float(string='Qty on Hand',
                            help='Quantity on Hand',
                            store=True)
    qty = fields.Float(string='Used')
    product_uom = fields.Many2one('product.uom', string='UOM', required=True)
    price_unit = fields.Float(string='Unit Cost')
    total = fields.Float(string='Total Cost', store=True)
    date_issued = fields.Datetime(string='Date issued')
    issued_by = fields.Many2one('res.users', string='Issued By',
                                default=lambda self: self._uid)
    is_deliver = fields.Boolean(string="Is Deliver?")

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id:
            prod = self.product_id
            if prod.in_active_part == True:
                self.product_id = False
                raise Warning(_('You can\'t select \
                         part which is In-Active!'))
            self.qty_hand = prod.qty_available
            self.product_uom = prod.uom_id
            self.price_unit = prod.list_price

    @api.onchange('qty', 'price_unit')
    def _onchange_qty(self):
        if self.product_id and self.qty and self.price_unit:
            self.total = self.qty * self.price_unit

    @api.constrains('qty')
    def _check_used_qty(self):
        for rec in self:
            if rec.qty <= 0:
                raise Warning(_('You can\'t \
                            enter used qty as Zero!'))
            # if rec.product_id.qty_available < rec.qty:
            #     raise Warning(_("you can't used qty more then available!!"))
            # if rec.product_id.qty_available <= 0.0:
            #     raise Warning(
            #         _("You can't used QTY which is on hand not available!"))

    @api.model
    def create(self, vals):
        """
        Overridden create method to add the issuer
        of the part and the time when it was issued.
        -----------------------------------------------------------
        @param self : object pointer
        """
        product_obj = self.env['product.product']
        if not vals.get('issued_by', False):
            vals.update({'issued_by': self._uid})
        if not vals.get('date_issued', False):
            vals.update({'date_issued':
                         time.strftime(DEFAULT_SERVER_DATETIME_FORMAT)})

        if vals.get('fleet_service_id', False) and \
                vals.get('product_id', False):
            task_line_ids = self.search([
                ('fleet_service_id', '=', vals['fleet_service_id']),
                ('product_id', '=', vals['product_id'])])
            if task_line_ids:
                product_rec = product_obj.browse(vals['product_id'])
                warrnig = 'You can not have duplicate \
                            parts assigned !!!'
                raise Warning(_(warrnig))
        return super(TaskLine, self).create(vals)

    @api.multi
    def write(self, vals):
        """Overridden write method to add the issuer of the part
        and the time when it was issued.
        ---------------------------------------------------------------
        @param self : object pointer
        """
        if vals.get('product_id', False)\
            or vals.get('qty', False)\
            or vals.get('product_uom', False)\
            or vals.get('price_unit', False)\
                or vals.get('old_part_return') in (True, False):
            vals.update({
                'issued_by': self._uid,
                'date_issued': time.strftime(DEFAULT_SERVER_DATETIME_FORMAT)
            })
        return super(TaskLine, self).write(vals)

    @api.multi
    def unlink(self):
        for part in self:
            if part.fleet_service_id.state == 'done':
                raise Warning(_("You can't delete part those already used."))
            if part.is_deliver == True:
                raise Warning(_("You can't delete part those already used."))
        return super(TaskLine, self).unlink()

    @api.onchange('date_issued')
    def check_onchange_part_issue_date(self):
        context_keys = self._context.keys()
        if 'date_open' in context_keys and self.date_issued:
            date_open = self._context.get('date_open', False)
            current_date = time.strftime(DEFAULT_SERVER_DATE_FORMAT)
            if not self.date_issued >= date_open and \
                    not self.date_issued <= current_date:
                self.date_issued = False
                raise Warning(_('You can\t enter \
                        parts issue either open work order date or in \
                           between open work order date and current date!'))


class RepairType(models.Model):
    _name = 'repair.type'

    name = fields.Char(string='Repair Type', size=264,
                       translate=True)

    @api.multi
    def copy(self, default=None):
        raise Warning(_("You can't duplicate record!"))

    @api.multi
    def unlink(self):
        raise Warning(_("You can't delete record !"))


class ServiceRepairLine(models.Model):
    _name = 'service.repair.line'

    @api.constrains('date', 'target_date')
    def check_target_completion_date(self):
        for vehicle in self:
            if vehicle.issue_date and vehicle.target_date:
                if vehicle.target_date < vehicle.issue_date:
                    raise ValidationError('Target Completion Date Should Be \
                    Greater Than Issue Date.')

    @api.constrains('target_date', 'date_complete')
    def check_etic_date(self):
        for vehicle in self:
            if vehicle.target_date and vehicle.date_complete:
                if vehicle.target_date > vehicle.date_complete:
                    raise ValidationError('Target Date Should Be \
                    Less Than ETIC Date.')

    service_id = fields.Many2one('fleet.vehicle.log.services',
                                 ondelete='cascade')
    repair_type_id = fields.Many2one('repair.type', string='Repair Type')
    categ_id = fields.Many2one('service.category', string='Category')
    issue_date = fields.Date(string='Issued Date ')
    date_complete = fields.Date(related='service_id.date_complete',
                                string="Complete Date")
    target_date = fields.Date(string='Target Completion')
    complete = fields.Boolean(string='Completed')


class FleetServiceType(models.Model):
    _inherit = 'fleet.service.type'

    category = fields.Selection([('contract', 'Contract'),
                                 ('service', 'Service'), ('both', 'Both')],
                                required=False,
                                string='Category', help='Choose wheter the \
                                                service refer to contracts, \
                                                vehicle services or both')
    repair_type_ids = fields.Many2many('repair.type',
                                       'fleet_service_repair_type_rel',
                                       'service_type_id', 'reapir_type_id',
                                       string='Repair Type')
