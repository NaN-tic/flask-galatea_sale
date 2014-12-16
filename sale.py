from flask import Blueprint, render_template, current_app, abort, g, \
    url_for, request, session, redirect, flash
from galatea.tryton import tryton
from galatea.helpers import login_required
from flask.ext.babel import gettext as _, lazy_gettext
from flask.ext.paginate import Pagination

sale = Blueprint('sale', __name__, template_folder='templates')

DISPLAY_MSG = lazy_gettext('Displaying <b>{start} - {end}</b> of <b>{total}</b>')

SHOPS = current_app.config.get('TRYTON_SALE_SHOPS')
LIMIT = current_app.config.get('TRYTON_PAGINATION_SALE_LIMIT', 20)
STATE_EXCLUDE = current_app.config.get('TRYTON_SALE_STATE_EXCLUDE', [])

Sale = tryton.pool.get('sale.sale')

SALE_FIELD_NAMES = [
    'create_date', 'sale_date', 'reference', 'state',
    'untaxed_amount', 'tax_amount', 'total_amount',
    ]
SALE_STATES_TO_CANCEL =['draft', 'quotation']

@sale.route("/<id>", endpoint="sale")
@tryton.transaction()
def sale_detail(lang, id):
    '''Sale Detail

    Not required login decorator because create new sale
    anonymous users (not loggin in)
    '''
    customer = session.get('customer')
    if not session.get('logged_in'):
        session.pop('customer', None)

    sales = Sale.search([
        ('id', '=', id),
        ('shop', 'in', SHOPS),
        ('party', '=', customer),
        ('state', 'not in', STATE_EXCLUDE),
        ], limit=1)
    if not sales:
        abort(404)

    sale, = Sale.browse(sales)

    #breadcumbs
    breadcrumbs = [{
        'slug': url_for('my-account', lang=g.language),
        'name': _('My Account'),
        }, {
        'slug': url_for('.sales', lang=g.language),
        'name': _('Sales'),
        }, {
        'slug': url_for('.sale', lang=g.language, id=sale.id),
        'name': sale.reference or _('Not reference'),
        }]

    return render_template('sale.html',
            breadcrumbs=breadcrumbs,
            sale=sale,
            )

@sale.route("/cancel/", methods=["POST"], endpoint="cancel")
@tryton.transaction()
def sale_cancel(lang):
    'Sale Cancel'
    id = request.form.get('id')
    if not id:
        flash(_('Error when cancel. Select a sale to cancel.'), "danger")

    sales = Sale.search([
        ('id', '=', id),
        ('shop', 'in', SHOPS),
        ('party', '=', session['customer']),
        ], limit=1)
    if not sales:
        flash(_('Error when cancel. You not have permisions to cancel.'), "danger")

    sale, = sales
    if sale.state in SALE_STATES_TO_CANCEL:
        Sale.cancel([sale])
        flash(_('Sale "%s" was cancelled.' % (sale.rec_name)))
    else:
        flash(_('Error when cancel "%s". Your sale is in a state that not available ' \
            'to cancel. Contact Us.' % (sale.rec_name)), "danger")

    return redirect(url_for('.sale', id=id, lang=g.language))

@sale.route("/", endpoint="sales")
@login_required
@tryton.transaction()
def sale_list(lang):
    '''Sales'''

    try:
        page = int(request.args.get('page', 1))
    except ValueError:
        page = 1

    domain = [
        ('shop', 'in', SHOPS),
        ('party', '=', session['customer']),
        ('state', 'not in', STATE_EXCLUDE),
        ]
    total = Sale.search_count(domain)
    offset = (page-1)*LIMIT

    order = [
        ('sale_date', 'DESC'),
        ('id', 'DESC'),
        ]
    sales = Sale.search_read(
        domain, offset, LIMIT, order, SALE_FIELD_NAMES)

    pagination = Pagination(
        page=page, total=total, per_page=LIMIT, display_msg=DISPLAY_MSG, bs_version='3')

    #breadcumbs
    breadcrumbs = [{
        'slug': url_for('my-account', lang=g.language),
        'name': _('My Account'),
        }, {
        'slug': url_for('.sales', lang=g.language),
        'name': _('Sales'),
        }]

    return render_template('sales.html',
            breadcrumbs=breadcrumbs,
            pagination=pagination,
            sales=sales,
            )
