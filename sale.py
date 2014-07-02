from flask import Blueprint, render_template, current_app, abort, g, \
    url_for, request, session
from galatea.tryton import tryton
from galatea.utils import get_tryton_locale
from galatea.helpers import login_required
from flask.ext.babel import gettext as _
from flask.ext.paginate import Pagination

sale = Blueprint('sale', __name__, template_folder='templates')

DISPLAY_MSG = _('Displaying <b>{start} - {end}</b> {record_name} in total <b>{total}</b>')

shops = current_app.config.get('TRYTON_SALE_SHOPS')
limit = current_app.config.get('TRYTON_PAGINATION_SALE_LIMIT', 20)
state_exclude = current_app.config.get('TRYTON_SALE_STATE_EXCLUDE', [])

Sale = tryton.pool.get('sale.sale')

SALE_FIELD_NAMES = [
    'create_date', 'sale_date', 'reference', 'state',
    'untaxed_amount', 'tax_amount', 'total_amount',
    ]

@tryton.default_context
def default_context():
    context = {}
    context['language'] = get_tryton_locale(g.language)
    return context

@sale.route("/<id>", endpoint="sale")
@tryton.transaction()
def sale_detail(lang, id):
    '''Sale Detail
    
    Not required login decorator because create new sale
    anonymous users (not loggin in)
    '''

    sales = Sale.search([
        ('id', '=', id),
        ('shop', 'in', shops),
        ('party', '=', session['customer']),
        ('state', 'not in', state_exclude),
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
        ('shop', 'in', shops),
        ('party', '=', session['customer']),
        ('state', 'not in', state_exclude),
        ]
    total = Sale.search_count(domain)
    offset = (page-1)*limit

    order = [
        ('sale_date', 'DESC'),
        ('id', 'DESC'),
        ]
    sales = Sale.search_read(
        domain, offset, limit, order, SALE_FIELD_NAMES)

    pagination = Pagination(
        page=page, total=total, per_page=limit, display_msg=DISPLAY_MSG, bs_version='3')

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
