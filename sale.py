from flask import Blueprint, render_template, current_app, abort, g, \
    url_for, request, session, redirect, flash, jsonify, send_file
from galatea.tryton import tryton
from galatea.utils import slugify
from galatea.helpers import login_required, customer_required, manager_required
from galatea.csrf import csrf
from flask_babel import gettext as _, lazy_gettext, ngettext
from flask_paginate import Pagination
from trytond.transaction import Transaction
from trytond.exceptions import UserError
import tempfile

sale = Blueprint('sale', __name__, template_folder='templates')

DISPLAY_MSG = lazy_gettext('Displaying <b>{start} - {end}</b> of <b>{total}</b>')

SHOP = current_app.config.get('TRYTON_SALE_SHOP')
SHOPS = current_app.config.get('TRYTON_SALE_SHOPS')
LIMIT = current_app.config.get('TRYTON_PAGINATION_SALE_LIMIT', 20)
LIMIT_WISHLIST = current_app.config.get('TRYTON_PAGINATION_WISHLIST_LIMIT', 20)
LIMIT_LAST_PRODUCTS = current_app.config.get('TRYTON_PAGINATION_LAST_PRODUCTS_LIMIT', 20)
LIMIT_TOTAL_LAST_PRODUCTS = current_app.config.get('TRYTON_TOTAL_LAST_PRODUCTS_LIMIT', 200)
STATE_EXCLUDE = current_app.config.get('TRYTON_SALE_STATE_EXCLUDE', [])
STATE_SALE_PRINT = current_app.config.get('TRYTON_SALE_PRINT', ['done'])

Sale = tryton.pool.get('sale.sale')
SaleReport = tryton.pool.get('sale.sale', type='report')
SaleWishlist = tryton.pool.get('sale.wishlist')
Product = tryton.pool.get('product.product')
GalateaUser = tryton.pool.get('galatea.user')
PartyAddress = tryton.pool.get('party.address')

SALE_STATES_TO_CANCEL = ['draft', 'quotation']

@sale.route("/print/<int:id>", endpoint="sale_print")
@login_required
@customer_required
@tryton.transaction()
def sale_print(lang, id):
    '''Sale Print'''

    domain = [
        ('id', '=', id),
        ('shop', 'in', SHOPS),
        ('state', 'in', STATE_SALE_PRINT),
        ]
    if not session.get('manager', False):
        if session.get('b2b'):
            domain += [['OR',
                ('party', '=', session['customer']),
                ('shipment_party', '=', session['customer'])
                ]]
        else:
            domain.append(('party', '=', session['customer']))

    sales = Sale.search(domain, limit=1)

    if not sales:
        abort(404)

    sale, = sales

    _, report, _, _ = SaleReport.execute([sale.id], {})
    report_name = 'sale-%s.pdf' % (slugify(sale.number) or 'sale')

    with tempfile.NamedTemporaryFile(
            prefix='%s-' % current_app.config['TRYTON_DATABASE'],
            suffix='.pdf', delete=False) as temp:
        temp.write(report)
    temp.close()
    data = open(temp.name, 'rb')

    return send_file(data, attachment_filename=report_name, as_attachment=True)

@sale.route("/admin/<int:id>", endpoint="admin-sale")
@manager_required
@tryton.transaction()
def admin_sale_detail(lang, id):
    '''Admin Sale Detail'''
    sales = Sale.search([
        ('id', '=', id),
        ], limit=1)
    if not sales:
        abort(404)

    sale, = Sale.browse(sales)

    #breadcumbs
    breadcrumbs = [{
        'slug': url_for('admin', lang=g.language),
        'name': _('Admin'),
        }, {
        'slug': url_for('.admin-sales', lang=g.language),
        'name': _('Sales'),
        }, {
        'slug': url_for('.admin-sale', lang=g.language, id=sale.id),
        'name': sale.number or _('Not reference'),
        }]

    return render_template('admin/sale.html',
            breadcrumbs=breadcrumbs,
            sale=sale,
            )

@sale.route("/admin/cancel/", methods=["POST"], endpoint="admin-cancel")
@manager_required
@csrf.exempt
@tryton.transaction()
def admin_sale_cancel(lang):
    '''Admin Sale Cancel'''
    id = request.form.get('id')
    if not id:
        flash(_('Error when cancel. Select a sale to cancel.'), "danger")

    sales = Sale.search([
        ('id', '=', id),
        ], limit=1)
    if not sales:
        flash(_('Error when cancel. You not have permisions to cancel.'), "danger")

    sale, = sales
    Sale.cancel([sale])
    flash(_('Sale "{sale}" was cancelled.').format(sale=sale.rec_name))

    return redirect(url_for('.admin-sale', id=id, lang=g.language))

@sale.route("/admin/", endpoint="admin-sales")
@manager_required
@tryton.transaction()
def admin_sale_list(lang):
    '''Admin Sales'''

    try:
        page = int(request.args.get('page', 1))
    except ValueError:
        page = 1

    if hasattr(Sale, 'get_flask_admin_sale_list_domain'):
        domain = Sale.get_flask_admin_sale_list_domain()
    else:
        domain = []
    q = request.args.get('q')
    if q:
        domain.append(('rec_name', 'ilike', '%'+q+'%'))
    party = request.args.get('party')
    if party:
        domain.append(('party', 'ilike', '%'+party+'%'))
    shipment_address = request.args.get('shipment_address')
    if shipment_address:
        shipment_address_id = PartyAddress.search(
            [('rec_name', 'ilike', '%'+shipment_address+'%')]
            )
        domain.append(('shipment_address', 'in', shipment_address_id))

    total = Sale.search_count(domain)
    offset = (page-1)*LIMIT

    order = [
        ('sale_date', 'DESC'),
        ('id', 'DESC'),
        ]
    sales = Sale.search(domain, offset, LIMIT, order)

    pagination = Pagination(
        page=page, total=total, per_page=LIMIT, display_msg=DISPLAY_MSG, bs_version='3')

    #breadcumbs
    breadcrumbs = [{
        'slug': url_for('admin', lang=g.language),
        'name': _('Admin'),
        }, {
        'slug': url_for('.admin-sales', lang=g.language),
        'name': _('Sales'),
        }]

    return render_template('admin/sales.html',
            breadcrumbs=breadcrumbs,
            pagination=pagination,
            sales=sales,
            q=q,
            party=party,
            shipment_address=shipment_address,
            )

@sale.route("/change-payment/", methods=["POST"], endpoint="change-payment")
@login_required
@customer_required
@tryton.transaction()
def change_payment(lang):
    '''Change Payment Type draft or quotation sales'''
    id = request.form.get('id')
    payment = request.form.get('payment')
    payment_type = None

    if not id:
        flash(_('Error when change payment. Select a sale to change payment.'), "danger")
        return redirect(url_for('.sales', lang=g.language))

    domain = [
        ('id', '=', id),
        ('shop', 'in', SHOPS),
        ('state', 'not in', STATE_EXCLUDE),
        ]
    if session.get('b2b'):
        domain += [['OR',
            ('party', '=', session['customer']),
            ('shipment_party', '=', session['customer'])
            ]]
    else:
        domain.append(('party', '=', session['customer']))

    sales = Sale.search(domain, limit=1)
    if not sales:
        flash(_('Error when change payment. You not have permisions to change payment.'), "danger")
        return redirect(url_for('.sales', lang=g.language))

    sale, = sales

    for p in sale.shop.esale_payments:
        if str(p.id) == payment:
            payment_type = p.payment_type
            break
    if not payment_type:
        flash(_('Error when change payment. Not available payment type current shop.'), "danger")
        return redirect(url_for('.sale', id=id, lang=g.language))

    if sale.state in ['draft', 'quotation']:
        current_state = sale.state
        if not current_state == 'draft':
            Sale.draft([sale])
        Sale.write([sale], {
            'payment_type': payment_type,
            })
        if not current_state == 'draft':
            try:
                Sale.quote([sale])
            except UserError as e:
                current_app.logger.info(e)
            except Exception as e:
                current_app.logger.info(e)
                flash(_('We found some errors when quote your sale.' \
                    'Contact Us.'), 'danger')
        flash('%s: %s' % (sale.rec_name, _('changed payment type.')))
    else:
        flash(_('Error when change payment type "{sale}". Your sale is in a state that not available ' \
            'to change payment type. Contact Us.'.format(sale=sale.rec_name)), "danger")

    return redirect(url_for('.sale', id=id, lang=g.language))

@sale.route("/<int:id>", endpoint="sale")
@tryton.transaction()
def sale_detail(lang, id):
    '''Sale Detail

    Not required login decorator because create new sale
    anonymous users (not loggin in)
    '''
    if not session.get('logged_in'):
        session.pop('customer', None)

    domain = [
        ('id', '=', id),
        ('shop', 'in', SHOPS),
        ('state', 'not in', STATE_EXCLUDE),
        ]
    if session.get('b2b'):
        domain += [['OR',
            ('party', '=', session['customer']),
            ('shipment_party', '=', session['customer'])
            ]]
    else:
        domain.append(('party', '=', session['customer']))

    sales = Sale.search(domain, limit=1)
    if not sales:
        if not session.get('logged_in'):
            session['next'] = url_for('.sale', lang=lang, id=id)
            try:
                url = url_for('portal.login', lang=lang)
            except:
                url = url_for('galatea.login', lang=lang)
            return redirect(url)
        else:
            abort(404)

    sale, = sales

    #breadcumbs
    breadcrumbs = [{
        'slug': url_for('my-account', lang=g.language),
        'name': _('My Account'),
        }, {
        'slug': url_for('.sales', lang=g.language),
        'name': _('Sales'),
        }, {
        'slug': url_for('.sale', lang=g.language, id=sale.id),
        'name': sale.number or _('Not reference'),
        }]

    return render_template('sale.html',
            breadcrumbs=breadcrumbs,
            sale=sale,
            )

@sale.route("/cancel/", methods=["POST"], endpoint="cancel")
@login_required
@customer_required
@tryton.transaction()
def sale_cancel(lang):
    '''Sale Cancel'''
    id = request.form.get('id')
    if not id:
        flash(_('Error when cancel. Select a sale to cancel.'), "danger")
        return redirect(url_for('.sales', lang=g.language))

    domain = [
        ('shop', 'in', SHOPS),
        ('state', 'not in', STATE_EXCLUDE),
        ]
    if session.get('b2b'):
        domain += [['OR',
            ('party', '=', session['customer']),
            ('shipment_party', '=', session['customer'])
            ]]
    else:
        domain.append(('party', '=', session['customer']))

    sales = Sale.search(domain, limit=1)
    if not sales:
        flash(_('Error when cancel. You not have permisions to cancel.'), "danger")
        return redirect(url_for('.sales', lang=g.language))

    sale, = sales
    if sale.state in SALE_STATES_TO_CANCEL:
        Sale.cancel([sale])
        flash(_('Sale "{sale}" was cancelled.'.format(sale=sale.rec_name)))
    else:
        flash(_('Error when cancel "{sale}". Your sale is in a state that not available ' \
            'to cancel. Contact Us.'.format(sale=sale.rec_name)), "danger")

    return redirect(url_for('.sale', id=id, lang=g.language))

@sale.route("/", endpoint="sales")
@login_required
@customer_required
@tryton.transaction()
def sale_list(lang):
    '''Sales'''

    try:
        page = int(request.args.get('page', 1))
    except ValueError:
        page = 1

    domain = [
        ('shop', 'in', SHOPS),
        ('state', 'not in', STATE_EXCLUDE),
        ]
    if session.get('b2b'):
        domain += [['OR',
            ('party', '=', session['customer']),
            ('shipment_party', '=', session['customer'])
            ]]
    else:
        domain.append(('party', '=', session['customer']))

    total = Sale.search_count(domain)
    offset = (page-1)*LIMIT

    order = [
        ('sale_date', 'DESC'),
        ('id', 'DESC'),
        ]
    sales = Sale.search(domain, offset, LIMIT, order)

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

@sale.route("/last-products", endpoint="last-products")
@login_required
@customer_required
@tryton.transaction()
def last_products(lang):
    '''Last products'''
    user = GalateaUser(session['user'])

    shipment_address = 'AND s.shipment_address=%s' % user.shipment_address.id  \
            if user.shipment_address else ''

    query = """
        SELECT
          DISTINCT(s.product)
        FROM (
            SELECT
              l.product FROM sale_sale s, sale_line l, product_product p,
              product_template t, product_template_sale_shop ts
            WHERE
              s.id = l.sale AND l.product = p.id AND p.template = t.id
              AND ts.template = t.id AND s.party=%(customer)s %(shipment_address)s
              AND l.product IS NOT NULL AND t.esale_available = true
              AND t.esale_active = true AND ts.shop in (%(shop)s)
            ORDER BY
              l.create_date DESC
            ) s
        LIMIT %(limit)s;
        """ % {
            'customer': session['customer'],
            'shipment_address': shipment_address,
            'limit': LIMIT_TOTAL_LAST_PRODUCTS,
            'shop': SHOP,
        }
    cursor = Transaction().connection.cursor()
    cursor.execute(query)
    results = [x[0] for x in cursor.fetchall()]

    # Get products from schema results
    try:
        page = int(request.args.get('page', 1))
    except ValueError:
        page = 1

    limit = LIMIT_LAST_PRODUCTS

    total = len(results)
    offset = (page-1)*LIMIT_LAST_PRODUCTS

    domain = [('id', 'in', results)]
    last_products = Product.search(domain, offset, limit)

    pagination = Pagination(page=page, total=total, per_page=limit, display_msg=DISPLAY_MSG, bs_version='3')

    breadcrumbs = [{
        'slug': url_for('my-account', lang=g.language),
        'name': _('My Account'),
        }, {
        'slug': url_for('.sales', lang=g.language),
        'name': _('Sales'),
        }, {
        'name': _('Last Products'),
        }]

    return render_template('sale-last-products.html',
        products=last_products,
        pagination=pagination,
        breadcrumbs=breadcrumbs,
    )

@sale.route('/wishlist/add', methods=['POST'], endpoint="wishlist-add")
@csrf.exempt
@login_required
@customer_required
@tryton.transaction()
def wishlist_add(lang):
    '''Add Wishlist products'''
    success = []
    warning = []

    ids = set()
    for data in request.json:
        if data.get('name'):
            prod = data.get('name').split('-')
            try:
                ids.add(int(prod[1]))
            except:
                continue

    ids = list(ids)
    if not ids:
        return jsonify(result=False)

    domain = [
        ('id', 'in', ids),
        ('esale_available', '=', True),
        ('esale_active', '=', True),
        ('shops', 'in', [SHOP]),
        ]
    products = Product.search(domain)

    domain = [
        ('party', '=', session['customer']),
        ('product', 'in', products),
        ]
    wishlists = SaleWishlist.search(domain)
    repeat_products = [w.product for w in wishlists]

    to_create = []
    for product in products:
        if product in repeat_products:
            warning.append(_('"{product}" already exists in your account.').format(
                product=product.rec_name))
            continue
        to_create.append({
            'party': session['customer'],
            'quantity': 1,
            'product': product,
            })

    if to_create:
        SaleWishlist.create(to_create)
        success.append(ngettext(
            '%(num)s product has been added in your account.',
            '%(num)s products have been added in your account.',
            len(to_create)))

    messages = {}
    messages['success'] = ",".join(success)
    messages['warning'] = ",".join(warning)

    return jsonify(result=True, messages=messages)

@sale.route("/wishlist", methods=["GET", "POST"], endpoint="wishlist")
@csrf.exempt
@login_required
@customer_required
@tryton.transaction()
def wishlist(lang):
    '''Wishlist products'''
    if request.method == 'POST':
        # Delete wishlists
        removes = request.form.getlist('remove')
        if removes:
            removes = list(set(int(r) for r in removes))
            to_remove = SaleWishlist.search([
                ('party', '=', session['customer']),
                ('id', 'in', removes),
                ])
            if to_remove:
                SaleWishlist.delete(to_remove)
                flash(ngettext(
                    '%(num)s wishlist has been deleted in your account.',
                    '%(num)s wishlists have been deleted in your account.',
                    len(to_remove)), 'success')

    try:
        page = int(request.args.get('page', 1))
    except ValueError:
        page = 1

    limit = LIMIT_WISHLIST

    domain = [
        ('party', '=', session['customer']),
        ('product.esale_available', '=', True),
        ('product.esale_active', '=', True),
        ('product.shops', 'in', [SHOP]),
        ]

    total = SaleWishlist.search_count(domain)
    offset = (page-1)*limit

    wishlists = SaleWishlist.search(domain, offset, limit)

    pagination = Pagination(page=page, total=total, per_page=limit, display_msg=DISPLAY_MSG, bs_version='3')

    breadcrumbs = [{
        'slug': url_for('my-account', lang=g.language),
        'name': _('My Account'),
        }, {
        'slug': url_for('.sales', lang=g.language),
        'name': _('Sales'),
        }, {
        'name': _('Wishlist'),
        }]

    return render_template('sale-wishlist.html',
        wishlists=wishlists,
        pagination=pagination,
        breadcrumbs=breadcrumbs,
    )
