"""Hàm dùng chung để đọc dữ liệu, kiểm chứng và tiền xử lý."""
from decimal import Decimal
from functools import cache, lru_cache
import hashlib
from pathlib import Path
import subprocess
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def file_sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def stable_digest(value):
    """Tính dấu vân tay cho cấu trúc Python, giữ thứ tự các dòng."""
    def freeze(item):
        if isinstance(item, dict):
            return tuple((key, freeze(item[key])) for key in sorted(item, key=repr))
        if isinstance(item, (list, tuple)):
            return tuple(map(freeze, item))
        return item

    return hashlib.sha256(repr(freeze(value)).encode("utf-8")).hexdigest()


def read_notebook(path):
    """Đọc các ô và kết quả đã lưu, dùng lại bản đã đọc nếu tệp còn nguyên."""
    path = Path(path).resolve()
    status = path.stat()
    return _saved_notebook(path, status.st_mtime_ns, status.st_size)


@lru_cache(maxsize=16)
def _saved_notebook(path, modified_ns, size):
    import nbformat

    return nbformat.read(path, as_version=4)


def notebook_prefix(cells):
    return stable_digest([
        (cell.get("id"), cell["cell_type"], "".join(cell["source"]))
        for cell in cells
    ])


def repository_status(root):
    if not (root / ".git").exists():
        return "Đang chạy từ bản giải nén."
    return subprocess.run(
        ["git", "status", "--short", "--untracked-files=all"],
        cwd=root, capture_output=True, text=True, check=True,
    ).stdout


def snapshot_files(root, excluded_notebook):
    """Hash tệp để so trạng thái trước và sau khi chạy."""
    root, excluded_notebook = Path(root).resolve(), Path(excluded_notebook).resolve()
    ignored = {".git", "__pycache__", ".ipynb_checkpoints"}
    return {
        path.relative_to(root).as_posix(): file_sha(path)
        for path in sorted(root.rglob("*"))
        if path.is_file() and path != excluded_notebook
        and not ignored.intersection(path.relative_to(root).parts)
    }


def raw_fingerprints(root):
    """Chụp dấu vân tay CSV hiện có để phát hiện thay đổi trong một lượt chạy."""
    return {path.name: file_sha(path) for path in (Path(root) / "data/raw").glob("*.csv")}


def read_model_parameters(base):
    import pandas as pd

    frame = pd.read_csv(base / "model_parameters.csv", float_precision="round_trip")
    features = ["Recency", "Frequency", "Monetary"]
    expected = {"center_id", "cluster", "variant", *(f"{prefix}_{f}" for prefix in ("center", "mean", "scale") for f in features)}
    if set(frame.columns) != expected or frame.empty or frame.variant.nunique() != 1:
        raise ValueError(f"Bảng tham số mô hình không hợp lệ: {base}")
    if sorted(frame.center_id.tolist()) != list(range(len(frame))) or not frame.cluster.is_unique:
        raise ValueError(f"Mã tâm cụm không hợp lệ: {base}")
    row = frame.iloc[0]
    return {
        "selected": {
            "variant": row.variant,
            "k": len(frame),
            "center_to_cluster": dict(zip(frame.center_id, frame.cluster)),
            "center_coordinates": frame[[f"center_{f}" for f in features]].to_numpy().tolist(),
            "scaler_mean": [row[f"mean_{f}"] for f in features],
            "scaler_scale": [row[f"scale_{f}"] for f in features],
        }
    }


def save_model_parameters(base, selected):
    import csv

    features = ("Recency", "Frequency", "Monetary")
    header = ["center_id", "cluster", "variant"]
    header += [f"{prefix}_{field}" for prefix in ("center", "mean", "scale") for field in features]
    with (base / "model_parameters.csv").open("x", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(header)
        for i, coordinates in enumerate(selected["center_coordinates"]):
            writer.writerow([i, selected["center_to_cluster"][i], selected["variant"],
                             *coordinates, *selected["scaler_mean"], *selected["scaler_scale"]])


def accepted_processed_outputs(directory, orders_schema, items_schema):
    """Tái sử dụng hai CSV. Đọc header ngắn, giữ nguyên tệp hiện có."""
    import csv

    schemas = {"orders_common": orders_schema, "order_items_common": items_schema}
    paths = {name: directory / f"{name}.csv" for name in schemas}
    present = {name for name, path in paths.items() if path.exists()}
    if not present:
        return {}
    if present != paths.keys():
        raise FileExistsError("Thiếu một CSV. Chọn OUTPUT_DIR khác để tạo lại cả cặp.")
    outputs = {}
    for name, path in paths.items():
        with path.open(encoding="utf-8", newline="") as stream:
            if next(csv.reader(stream), None) != list(schemas[name]):
                raise ValueError(f"Sai cấu trúc cột: {path}. Chọn OUTPUT_DIR khác để tạo lại.")
            if not any(stream.read(1)):
                raise ValueError(f"CSV không có dòng dữ liệu: {path}")
        outputs[name] = {"Tệp": str(path), "Trạng thái": "Dùng lại"}
    return outputs


SOURCE_TABLES = {
    'V01': ('orders', 'customers'),
    'V02': ('orders', 'order_items', 'payments', 'products', 'sales'),
    'V03': ('returns', 'orders', 'order_items', 'payments'),
    'V04': ('inventory', 'orders', 'order_items'),
    'V05': ('inventory',),
    'V06': ('order_items', 'promotions'),
    'V07': ('web_traffic',),
    'V08': ('web_traffic', 'customers'),
    'V09': ('sample_submission', 'sales'),
}


def verification_checks():
    return dict(V01=v01(), V02=v02(), V03=v03(), V04=v04(), V05=v05(),
                V06=v06(), V07=v07(), V08=v08(), V09=v09())


def kiem_chung_nguon(code):
    """Tính các chỉ tiêu từ CSV hiện tại và kiểm tra tệp không đổi trong lúc đọc."""
    code = code.upper()
    paths = {name: PROJECT_ROOT / "data/raw" / f"{name}.csv" for name in SOURCE_TABLES[code]}
    sources = {
        name: {"path": path.relative_to(PROJECT_ROOT).as_posix(), "sha256": file_sha(path)}
        for name, path in paths.items()
    }

    v = verification_checks()[code]
    result = {"sources": sources}
    if code == "V01":
        metrics, checks, _ = v.analyze(**{name: v.read_table(path) for name, path in paths.items()})
        result["date_formats"] = v.FORMATS.copy()
        status = "ok"
    elif code == "V02":
        metrics, checks, tables, _ = v.analyze(**v.read_sources(paths))
        comparisons = tables["comparisons"]
        name = "order_payment_vs_gross_minus_discount"
        comparison = comparisons.loc[comparisons.comparison.eq(name)].iloc[0].to_dict()
        differences = tables["order_ledger"].payment_difference.dropna()
        comparison["exact_match_cases"] = int(differences.eq(0).sum())
        comparison["nonzero_difference_cases"] = int(differences.ne(0).sum())
        result["reports"] = {"statuses": {"records": tables["statuses"].to_dict("records")},
                             "comparisons": {"records": [comparison]}}
        result["tolerance"] = v.TOLERANCE
        status = "ok"
    elif code == "V03":
        metrics, checks, *_ = v.analyze(**v.read_sources(paths))
        result["tolerance"] = v.TOLERANCE
        status = "completed_with_findings"
    elif code == "V04":
        metrics, checks, ledgers, _, _ = v.analyze(**v.read_sources(paths))
        examples, _ = v.compact_examples(ledgers["quantity"], 1)
        result["examples"] = {
            "largest_absolute_differences": {"records": examples["largest_absolute_differences"].to_dict("records")}
        }
        status = "completed_with_differences"
    elif code == "V05":
        inventory = v.read_source(paths["inventory"])
        metrics, tables, _, _ = v.analyze(inventory)
        checks = {
            "distribution_partitions_all_rows": int(tables["reorder_distribution"].rows.sum()) == len(inventory),
            "condition_groups_cover_eligible_and_unknown": all(
                row.selected_rows + row.not_selected_rows + row.unknown_predictor_rows == len(inventory)
                for row in tables["condition_summary"].itertuples()
            ),
        }
        status = "completed_with_assessment"
    else:
        if code == "V07":
            analysis = v.analyze(v.read_source(paths["web_traffic"]))
        else:
            analysis = v.analyze(**v06().read_sources(paths))
        metrics, checks = analysis["metrics"], analysis["checks"]
        status = "completed_with_findings" if code == "V06" else "completed_with_assessment"

    for name, path in paths.items():
        if file_sha(path) != sources[name]["sha256"]:
            raise ValueError(f"{code}: {path.name} thay đổi trong lúc kiểm chứng")
    return dict(result, metrics=metrics, checks=checks, status=status if all(checks.values()) else "failed")


@cache
def v01():
    """V01: compare order dates with customer signup dates without altering sources."""

    import argparse
    import csv
    import hashlib
    import math
    import re
    import statistics
    import sys
    from collections import Counter
    from datetime import datetime, timezone
    from functools import lru_cache
    from pathlib import Path

    import pandas as pd

    read_table = table_reader().read_table


    ROOT = PROJECT_ROOT
    FORMATS = {'order_date': '%Y-%m-%d', 'signup_date': '%Y-%m-%d'}
    PATTERNS = {'order_date': r'\d{4}-\d{2}-\d{2}', 'signup_date': r'\d{4}-\d{2}-\d{2}'}


    def digest(path):
        with path.open('rb') as stream:
            return hashlib.file_digest(stream, 'sha256').hexdigest()


    def parse_date(series, column):
        text = series.astype('string')
        syntax = text.str.fullmatch(PATTERNS[column], na=False)
        parsed = pd.to_datetime(text.where(syntax), format=FORMATS[column], errors='coerce')
        invalid = series.notna() & parsed.isna()
        report = dict(column=column, format=FORMATS[column], rows=len(series),
                      null_count=int(series.isna().sum()), syntax_invalid_count=int((series.notna() & ~syntax).sum()),
                      invalid_non_null_count=int(invalid.sum()), valid_count=int(parsed.notna().sum()),
                      invalid_examples=repr(text[invalid].head(5).tolist()),
                      min_date=parsed.min().date().isoformat() if parsed.notna().any() else None,
                      max_date=parsed.max().date().isoformat() if parsed.notna().any() else None)
        return parsed, report


    def analyze(orders, customers, examples=20):
        """Compute on all rows; reject ambiguous customer mappings before merging."""
        if examples < 1:
            raise ValueError('examples must be positive')
        orders = orders[['order_id', 'customer_id', 'order_date']].copy()
        customers = customers[['customer_id', 'signup_date']].copy()
        values = {}
        for table, frame in [('orders', orders), ('customers', customers)]:
            values[f'{table}_rows'] = len(frame)
            values[f'{table}_distinct_customer_ids'] = int(frame.customer_id.nunique())
            values[f'{table}_null_customer_ids'] = int(frame.customer_id.isna().sum())
            values[f'{table}_duplicate_customer_ids_excess'] = int(frame.customer_id.dropna().duplicated().sum())
        values['orders_distinct_order_ids'] = int(orders.order_id.nunique())
        values['orders_null_order_ids'] = int(orders.order_id.isna().sum())
        values['orders_duplicate_order_ids_excess'] = int(orders.order_id.dropna().duplicated().sum())
        if values['customers_duplicate_customer_ids_excess']:
            raise ValueError('customers.customer_id is not unique: '
                             f'{values["customers_duplicate_customer_ids_excess"]} excess rows; join refused (no deduplication)')
        orders['order_parsed'], order_dates = parse_date(orders.order_date, 'order_date')
        customers['signup_parsed'], signup_dates = parse_date(customers.signup_date, 'signup_date')
        # Exclude NULL keys on the right so pandas cannot match NULL with NULL.
        joined = orders.merge(customers[customers.customer_id.notna()], on='customer_id',
                              how='left', validate='many_to_one', indicator=True, sort=False)
        values['joined_rows'] = len(joined)
        missing_id = joined.customer_id.isna()
        orphan = ~missing_id & joined['_merge'].eq('left_only')
        values['orphan_orders'] = int(orphan.sum())
        values['orphan_distinct_customer_ids'] = int(joined.loc[orphan, 'customer_id'].nunique())
        joined['comparison'] = 'uncomparable'
        joined['exclusion_reason'] = ''
        # Ordered reasons partition excluded orders without double counting.
        for mask, reason in [(missing_id, 'missing_customer_id'), (orphan, 'orphan_customer_id'),
                             (joined.order_parsed.isna(), 'missing_or_invalid_order_date'),
                             (joined.signup_parsed.isna(), 'missing_or_invalid_signup_date')]:
            select = mask & joined.exclusion_reason.eq('')
            joined.loc[select, 'exclusion_reason'] = reason
            values[f'excluded_{reason}'] = int(select.sum())
        valid = joined.exclusion_reason.eq('')
        signed = (joined.order_parsed - joined.signup_parsed).dt.days
        for name, mask in [('before', signed.lt(0)), ('equal', signed.eq(0)), ('after', signed.gt(0))]:
            joined.loc[valid & mask, 'comparison'] = name
            count = int((valid & mask).sum())
            values[f'{name}_orders'] = count
            values[f'{name}_percent_all_orders'] = 100 * count / len(orders) if len(orders) else None
            values[f'{name}_percent_comparable_orders'] = 100 * count / int(valid.sum()) if valid.any() else None
        values['comparable_orders'] = int(valid.sum())
        values['uncomparable_orders'] = int((~valid).sum())
        before = joined[joined.comparison.eq('before')].copy()
        before['gap_days'] = -signed.loc[before.index]
        values['customers_with_before_orders'] = int(before.customer_id.nunique())
        gaps = before.gap_days
        for name, value in [('min', gaps.min()), ('max', gaps.max()), ('mean', gaps.mean()), ('median', gaps.median())]:
            values[f'before_gap_{name}_days'] = float(value) if pd.notna(value) else None
        for quantile in [.05, .25, .50, .75, .95, .99]:
            values[f'before_gap_p{int(quantile * 100):02d}_days'] = float(gaps.quantile(quantile)) if len(gaps) else None
        joined['order_year'] = joined.order_parsed.dt.year.astype('Int64')
        joined['signup_year'] = joined.signup_parsed.dt.year.astype('Int64')
        distributions = []
        for grouping, keys in [('order_year', ['order_year']), ('signup_year', ['signup_year']),
                                ('year_pair', ['order_year', 'signup_year'])]:
            distribution = joined.groupby(keys + ['comparison'], dropna=False).size().rename('orders').reset_index()
            distribution['percent_within_period'] = 100 * distribution.orders / distribution.groupby(keys, dropna=False).orders.transform('sum')
            distribution['grouping'] = grouping
            distributions.append(distribution)
        temporal = pd.concat(distributions, ignore_index=True).reindex(
            columns=['grouping', 'order_year', 'signup_year', 'comparison', 'orders', 'percent_within_period'])
        # Stable ties in source order; examples are a purposeful sample, not prevalence estimates.
        sample = before.sort_values('gap_days', ascending=False, kind='stable').head(examples).copy()
        sample['order_date_iso'] = sample.order_parsed.dt.strftime('%Y-%m-%d')
        sample['signup_date_iso'] = sample.signup_parsed.dt.strftime('%Y-%m-%d')
        sample = sample[['order_id', 'customer_id', 'order_date', 'signup_date', 'order_date_iso', 'signup_date_iso', 'gap_days']]
        diagnostics = joined[joined.exclusion_reason.ne('')].head(examples)[
            ['order_id', 'customer_id', 'order_date', 'signup_date', 'exclusion_reason']]
        checks = {
            'customer_link_key_unique_non_null': bool(len(customers) and not values['customers_null_customer_ids']),
            'order_id_unique_non_null': bool(len(orders) and not values['orders_null_order_ids'] and not values['orders_duplicate_order_ids_excess']),
            'join_preserves_rows': len(joined) == len(orders),
            'no_missing_order_customer_id': values['orders_null_customer_ids'] == 0,
            'no_orphan_orders': values['orphan_orders'] == 0,
            'order_dates_valid_non_null': order_dates['null_count'] + order_dates['invalid_non_null_count'] == 0,
            'signup_dates_valid_non_null': signup_dates['null_count'] + signup_dates['invalid_non_null_count'] == 0,
            'comparison_partition_complete': sum(values[f'{n}_orders'] for n in ['before', 'equal', 'after', 'uncomparable']) == len(orders),
        }
        return values, checks, {'date_validation': pd.DataFrame([order_dates, signup_dates]),
                                'time_distribution': temporal, 'largest_gaps': sample,
                                'excluded_examples': diagnostics}
    return SimpleNamespace(
        argparse=argparse,
        csv=csv,
        hashlib=hashlib,
        math=math,
        re=re,
        statistics=statistics,
        sys=sys,
        Counter=Counter,
        datetime=datetime,
        timezone=timezone,
        lru_cache=lru_cache,
        Path=Path,
        pd=pd,
        read_table=read_table,
        ROOT=ROOT,
        FORMATS=FORMATS,
        PATTERNS=PATTERNS,
        digest=digest,
        parse_date=parse_date,
        analyze=analyze,
    )


@cache
def v02():
    """V02: source-backed financial reconciliation, all order statuses included."""

    import argparse
    import csv
    import hashlib
    import sys
    from collections import defaultdict
    from datetime import datetime, timezone
    from decimal import Decimal, InvalidOperation
    from pathlib import Path

    import pandas as pd

    read_table = table_reader().read_table
    NA_TOKENS = source_profiles().NA_TOKENS


    ROOT = PROJECT_ROOT
    TOLERANCE = Decimal('0.05')
    ZERO = Decimal(0)
    FIELDS = ['gross', 'discount', 'payment', 'cogs']
    COLUMNS = {
        'orders': ['order_id', 'order_date', 'order_status'],
        'order_items': ['order_id', 'product_id', 'quantity', 'unit_price', 'discount_amount'],
        'payments': ['order_id', 'payment_value'],
        'products': ['product_id', 'cogs'],
        'sales': ['Date', 'Revenue', 'COGS'],
    }
    MONEY = {'order_items': ['quantity', 'unit_price', 'discount_amount'],
             'payments': ['payment_value'], 'products': ['cogs'], 'sales': ['Revenue', 'COGS']}
    # Reference targets only: every actual value is recomputed from source CSVs.


    def digest(path):
        with path.open('rb') as stream:
            return hashlib.file_digest(stream, 'sha256').hexdigest()


    def decimal_value(value):
        try:
            result = Decimal(str(value))
        except InvalidOperation as exc:
            raise ValueError(f'Invalid numeric value: {value!r}') from exc
        if not result.is_finite():
            raise ValueError(f'Missing/non-finite numeric value: {value!r}')
        return result


    def read_sources(paths):
        frames = {}
        for name, path in paths.items():
            # Reuse structural CSV validation and exact string identifiers.
            frame = read_table(path)
            if name in MONEY:
                # Read source lexemes as strings, avoiding float inference before Decimal.
                exact = pd.read_csv(path, encoding='utf-8-sig', usecols=MONEY[name],
                                    dtype='string', skip_blank_lines=False)
                for column in MONEY[name]:
                    frame[column] = exact[column]
            frames[name] = frame
        return frames


    def require_key(frame, column, table):
        nulls = int(frame[column].isna().sum())
        duplicates = int(frame[column].dropna().duplicated().sum())
        if nulls or duplicates:
            raise ValueError(f'{table}.{column}: null={nulls}, duplicate_excess={duplicates}; join refused')
        return dict(table=table, key=column, rows=len(frame), null_keys=nulls,
                    duplicate_keys_excess=duplicates)


    def require_link(child, parent, key, relation):
        nulls = int(child[key].isna().sum())
        orphan = int((child[key].notna() & ~child[key].isin(parent[key])).sum())
        if nulls or orphan:
            raise ValueError(f'{relation}: null_keys={nulls}, orphan_rows={orphan}; join refused')
        return dict(relation=relation, child_rows=len(child), null_keys=nulls, orphan_rows=orphan)


    def dates(series, name):
        text = series.astype('string')
        parsed = pd.to_datetime(text.where(text.str.fullmatch(r'\d{4}-\d{2}-\d{2}', na=False)),
                                format='%Y-%m-%d', errors='coerce')
        if parsed.isna().any():
            raise ValueError(f'{name}: {int(parsed.isna().sum())} missing/invalid ISO dates; no rows excluded')
        return parsed.dt.strftime('%Y-%m-%d')


    def compare(frame, actual, expected, name):
        """Exact absolute tolerance, including its boundary; no intermediate rounding."""
        valid = frame[actual].notna() & frame[expected].notna()
        difference = pd.Series(None, index=frame.index, dtype=object)
        difference.loc[valid] = frame.loc[valid, actual] - frame.loc[valid, expected]
        absolute = difference.loc[valid].abs()
        over = absolute.gt(TOLERANCE)
        return dict(comparison=name, cases=len(frame), compared_cases=int(valid.sum()),
                    missing_cases=int((~valid).sum()), over_tolerance_count=int(over.sum()),
                    max_abs_difference=max(absolute, default=ZERO),
                    tolerance=TOLERANCE), difference


    def ledger_fingerprint(frame, key):
        """Canonical digest of every aggregate, not a sample or rounded monetary value."""
        result = hashlib.sha256()
        for row in frame.sort_values(key).itertuples(index=False):
            values = row._asdict()
            record = [str(values[key]), *[format(values[f].normalize(), 'f') for f in FIELDS]]
            result.update((repr(record) + '\n').encode('utf-8'))
        return result.hexdigest()


    def analyze(orders, order_items, payments, products, sales):
        """Validate keys first; aggregate children before joining; never filter status."""
        frames = {name: frame[COLUMNS[name]].copy() for name, frame in
                  zip(COLUMNS, [orders, order_items, payments, products, sales])}
        orders, items, payments, products, sales = (frames[n] for n in COLUMNS)
        if any(frame.empty for frame in frames.values()):
            raise ValueError('All five source tables must be non-empty')
        keys = [require_key(orders, 'order_id', 'orders'),
                require_key(products, 'product_id', 'products')]
        orders['order_date'] = dates(orders.order_date, 'orders.order_date')
        sales['Date'] = dates(sales.Date, 'sales.Date')
        keys.append(require_key(sales, 'Date', 'sales'))
        links = [require_link(items, orders, 'order_id', 'order_items -> orders'),
                 require_link(items, products, 'product_id', 'order_items -> products'),
                 require_link(payments, orders, 'order_id', 'payments -> orders')]
        for name, columns in MONEY.items():
            for column in columns:
                try:
                    frames[name][column] = frames[name][column].map(decimal_value)
                except ValueError as exc:
                    raise ValueError(f'{name}.{column}: {exc}') from exc
        # Both joins are many-to-one; repeated item/product combinations are not deduplicated.
        items = items.merge(products, on='product_id', how='left', validate='many_to_one')
        items['gross'] = items.quantity * items.unit_price
        items['discount'] = items.discount_amount
        items['cogs'] = items.quantity * items.cogs
        line_totals = items.groupby('order_id', sort=False)[['gross', 'discount', 'cogs']].sum()
        payment_totals = payments.groupby('order_id', sort=False).payment_value.sum().rename('payment')
        ledger = orders.merge(line_totals, on='order_id', how='left', validate='one_to_one')
        ledger = ledger.merge(payment_totals, on='order_id', how='left', validate='one_to_one')
        missing_items = int((~orders.order_id.isin(items.order_id)).sum())
        missing_payments = int((~orders.order_id.isin(payments.order_id)).sum())
        # Absent children count as zero in the all-order ledger, with failed coverage checks.
        for field in FIELDS:
            ledger[field] = ledger[field].where(ledger[field].notna(), ZERO)
        ledger['net'] = ledger.gross - ledger.discount
        order_summary, ledger['payment_difference'] = compare(ledger, 'payment', 'net', 'order_payment_vs_gross_minus_discount')
        daily = ledger.groupby('order_date', sort=True)[FIELDS].sum().reset_index().rename(columns={'order_date': 'date'})
        daily_computed = daily.copy()
        daily = daily.merge(sales.rename(columns={'Date': 'date', 'Revenue': 'sales_revenue', 'COGS': 'sales_cogs'}),
                            on='date', how='outer', validate='one_to_one', indicator=True).sort_values('date')
        daily['sales_revenue_minus_payment'] = [a - b if pd.notna(a) and pd.notna(b) else None
                                                 for a, b in zip(daily.sales_revenue, daily.payment)]
        summaries = [order_summary]
        for actual, expected, name in [
                ('sales_revenue', 'gross', 'daily_revenue_vs_item_gross'),
                ('sales_cogs', 'cogs', 'daily_cogs_vs_quantity_product_cogs'),
                ('sales_revenue_minus_payment', 'discount', 'daily_revenue_minus_payment_vs_discount')]:
            summary, difference = compare(daily, actual, expected, name)
            daily[name + '_difference'] = difference
            summaries.append(summary)
        daily['coverage'] = daily.pop('_merge').astype(str)
        statuses = ledger.groupby('order_status', dropna=False, sort=True)[FIELDS].sum().reset_index()
        counts = ledger.groupby('order_status', dropna=False).size().rename('orders')
        statuses = statuses.merge(counts, on='order_status', validate='one_to_one')
        item_status = items.merge(orders[['order_id', 'order_status']], on='order_id', validate='many_to_one')
        line_counts = item_status.groupby('order_status', dropna=False).size().rename('item_rows')
        statuses = statuses.merge(line_counts, on='order_status', how='left', validate='one_to_one')
        statuses['item_rows'] = statuses.item_rows.fillna(0).astype(int)
        metrics = dict(orders_rows=len(orders), order_items_rows=len(items), payments_rows=len(payments),
                       products_rows=len(products), sales_days=len(sales), computed_days=len(daily_computed),
                       orders_without_items=missing_items, orders_without_payments=missing_payments,
                       payment_duplicate_order_ids_excess=int(payments.order_id.duplicated().sum()),
                       null_order_status=int(orders.order_status.isna().sum()),
                       sales_only_days=int(daily.coverage.eq('right_only').sum()),
                       orders_only_days=int(daily.coverage.eq('left_only').sum()))
        metrics.update({field: sum(ledger[field], ZERO) for field in FIELDS})
        metrics.update(sales_revenue=sum(sales.Revenue, ZERO), sales_cogs=sum(sales.COGS, ZERO))
        metrics['net'] = metrics['gross'] - metrics['discount']
        metrics['revenue_minus_payment'] = metrics['sales_revenue'] - metrics['payment']
        totals = pd.DataFrame([metrics])
        for actual, expected, name in [('payment', 'net', 'total_payment_vs_gross_minus_discount'),
                                      ('sales_revenue', 'gross', 'total_revenue_vs_item_gross'),
                                      ('sales_cogs', 'cogs', 'total_cogs_vs_quantity_product_cogs'),
                                      ('revenue_minus_payment', 'discount', 'total_revenue_minus_payment_vs_discount')]:
            summaries.append(compare(totals, actual, expected, name)[0])
        checks = dict(item_join_preserves_rows=len(items) == len(order_items),
                      order_join_preserves_rows=len(ledger) == len(orders),
                      all_orders_have_items=missing_items == 0, all_orders_have_payments=missing_payments == 0,
                      day_coverage_matches=metrics['sales_only_days'] == metrics['orders_only_days'] == 0,
                      status_counts_partition_orders=int(statuses.orders.sum()) == len(orders),
                      status_counts_partition_items=int(statuses.item_rows.sum()) == len(items))
        for row in summaries:
            checks[row['comparison']] = row['missing_cases'] == row['over_tolerance_count'] == 0
        fingerprints = {'orders': ledger_fingerprint(ledger, 'order_id'),
                        'daily': ledger_fingerprint(daily_computed, 'date')}
        # Nullable statuses are preserved in reports; use a stable sentinel only for audit hashing.
        status_ledger = statuses.copy()
        status_ledger['order_status'] = status_ledger.order_status.fillna('<NULL>')
        fingerprints['statuses'] = ledger_fingerprint(status_ledger, 'order_status')
        return metrics, checks, dict(order_ledger=ledger, daily=daily, statuses=statuses,
                                     key_integrity=pd.DataFrame(keys), foreign_keys=pd.DataFrame(links),
                                     comparisons=pd.DataFrame(summaries)), fingerprints


    def compact_reports(metrics, reports, examples=20):
        """Summarize full in-memory ledgers; persist bounded exceptions and maxima only."""
        if examples < 1:
            raise ValueError('examples must be positive')
        exported = {name: frame for name, frame in reports.items()
                    if name not in {'order_ledger', 'daily', 'comparisons'}}
        ledger, daily = reports['order_ledger'], reports['daily']
        daily_names = ['daily_revenue_vs_item_gross', 'daily_cogs_vs_quantity_product_cogs',
                       'daily_revenue_minus_payment_vs_discount']
        differences = {'order_payment_vs_gross_minus_discount': ledger.payment_difference}
        differences.update({name: daily[name + '_difference'] for name in daily_names})
        for name, actual, expected in [
                ('total_payment_vs_gross_minus_discount', 'payment', 'net'),
                ('total_revenue_vs_item_gross', 'sales_revenue', 'gross'),
                ('total_cogs_vs_quantity_product_cogs', 'sales_cogs', 'cogs'),
                ('total_revenue_minus_payment_vs_discount', 'revenue_minus_payment', 'discount')]:
            differences[name] = pd.Series([metrics[actual] - metrics[expected]], dtype=object)
        summaries = reports['comparisons'].to_dict('records')
        for row in summaries:
            valid = differences[row['comparison']].dropna()
            absolute = valid.abs()
            exact = int(valid.eq(ZERO).sum())
            row.update(exact_match_cases=exact, nonzero_difference_cases=len(valid) - exact,
                       matched_cases=row['compared_cases'] - row['over_tolerance_count'],
                       mismatched_cases=row['over_tolerance_count'] + row['missing_cases'],
                       within_tolerance_nonzero_cases=len(valid) - exact - row['over_tolerance_count'],
                       min_signed_difference=min(valid, default=None),
                       max_signed_difference=max(valid, default=None),
                       sum_signed_difference=sum(valid, ZERO),
                       mean_abs_difference=sum(absolute, ZERO) / len(valid) if len(valid) else None)
        exported['comparisons'] = pd.DataFrame(summaries)
        bad_orders = ledger[ledger.payment_difference.abs().gt(TOLERANCE)]
        exported['order_mismatch_examples'] = bad_orders.sort_values(
            'payment_difference', key=lambda x: x.abs(), ascending=False, kind='stable').head(examples)
        exported['order_exception_summary'] = pd.DataFrame([dict(
            exception_count=len(bad_orders), examples_reported=min(len(bad_orders), examples),
            examples_omitted=max(0, len(bad_orders) - examples))])
        columns = [name + '_difference' for name in daily_names]
        over = pd.DataFrame({c: daily[c].map(lambda v: pd.notna(v) and abs(v) > TOLERANCE)
                             for c in columns}, index=daily.index).any(axis=1)
        missing = daily[columns].isna().any(axis=1) | daily.coverage.ne('both')
        nonzero = pd.DataFrame({c: daily[c].map(lambda v: pd.notna(v) and v != ZERO)
                                for c in columns}, index=daily.index).any(axis=1)
        exceptions = daily[over | missing]
        # Source date order makes truncation deterministic. Counts always describe all days.
        exported['daily_exception_examples'] = exceptions.head(examples)
        exported['daily_summary'] = pd.DataFrame([dict(
            days=len(daily), first_date=daily.date.min(), last_date=daily.date.max(),
            covered_days=int(daily.coverage.eq('both').sum()),
            exact_match_days=int((~nonzero & ~missing).sum()),
            matched_days=int((~over & ~missing).sum()), mismatched_days=int((over | missing).sum()),
            over_tolerance_days=int(over.sum()), missing_days=int(missing.sum()),
            nonzero_difference_days=int(nonzero.sum()),
            exception_count=len(exceptions), examples_reported=min(len(exceptions), examples),
            examples_omitted=max(0, len(exceptions) - examples))])
        maxima = []
        for name in daily_names:
            column = name + '_difference'
            nonzero_values = daily.loc[daily[column].notna() & daily[column].ne(ZERO), column]
            if len(nonzero_values):
                index = nonzero_values.sort_values(key=lambda x: x.abs(), ascending=False, kind='stable').index[0]
                maxima.append(dict(comparison=name, **daily.loc[index].to_dict()))
        exported['daily_max_difference_examples'] = pd.DataFrame(maxima, columns=['comparison', *daily.columns])
        return exported
    return SimpleNamespace(
        argparse=argparse,
        csv=csv,
        hashlib=hashlib,
        sys=sys,
        defaultdict=defaultdict,
        datetime=datetime,
        timezone=timezone,
        Decimal=Decimal,
        InvalidOperation=InvalidOperation,
        Path=Path,
        pd=pd,
        read_table=read_table,
        NA_TOKENS=NA_TOKENS,
        ROOT=ROOT,
        TOLERANCE=TOLERANCE,
        ZERO=ZERO,
        FIELDS=FIELDS,
        COLUMNS=COLUMNS,
        MONEY=MONEY,
        digest=digest,
        decimal_value=decimal_value,
        read_sources=read_sources,
        require_key=require_key,
        require_link=require_link,
        dates=dates,
        compare=compare,
        ledger_fingerprint=ledger_fingerprint,
        analyze=analyze,
        compact_reports=compact_reports,
    )


@cache
def v03():
    """V03 returns checks on complete CSV sources; bounded, reproducible evidence."""

    import argparse
    import csv
    import hashlib
    import math
    import statistics
    import sys
    from collections import Counter, defaultdict
    from datetime import datetime, timezone
    from decimal import Decimal
    from pathlib import Path

    import pandas as pd

    ZERO = v02().ZERO
    TOLERANCE = v02().TOLERANCE
    dates = v02().dates
    decimal_value = v02().decimal_value
    digest = v02().digest
    require_key = v02().require_key
    require_link = v02().require_link
    NA_TOKENS = source_profiles().NA_TOKENS
    read_table = table_reader().read_table


    ROOT = PROJECT_ROOT
    PAIR = ['order_id', 'product_id']
    COLUMNS = {
        'returns': ['return_id', *PAIR, 'return_date', 'return_reason', 'return_quantity', 'refund_amount'],
        'orders': ['order_id', 'order_date', 'order_status'],
        'order_items': [*PAIR, 'quantity', 'unit_price', 'discount_amount'],
        'payments': ['order_id', 'payment_value'],
    }
    NUMERIC = {'returns': ['return_quantity', 'refund_amount'],
               'order_items': ['quantity', 'unit_price', 'discount_amount'], 'payments': ['payment_value']}
    PAIR_FIELDS = [*PAIR, 'returned_quantity', 'refund', 'return_rows', 'purchased_quantity',
                   'gross', 'discount', 'item_rows', 'min_price', 'max_price',
                   'quantity_difference', 'expected_gross_refund', 'expected_net_refund',
                   'gross_refund_difference', 'net_refund_difference', 'net_purchased',
                   'gross_purchased_difference', 'net_purchased_difference', 'refund_ratio', 'discount_rate']
    ORDER_FIELDS = ['order_id', 'refund', 'return_rows', 'returned_quantity', 'payment', 'payment_difference']
    RETURN_FIELDS = [*COLUMNS['returns'], 'order_status', 'lag_days']
    PRESENCE_FIELDS = ['order_id', 'order_date', 'order_status', 'has_return', 'days_to_last_return']
    SECTIONS = {
        'V03.1': 'Keys, values, chronology, order status/presence and cumulative refund vs payment',
        'V03.2': 'Purchased products, cumulative returned quantity and purchased gross/net bounds',
        'V03.3': 'GrossReturn/NetReturn, full/partial returns and end-of-data diagnostics',
        'V03.4': 'RefundRatio distribution, discount groups and Pearson correlation',
    }
    DEFINITIONS = [
        ('V03.1', 'returns_on_nonreturned_status', 'returns', 'status_difference', ZERO, True),
        ('V03.1', 'returned_orders_without_returns', 'presence', 'presence_difference', ZERO, True),
        ('V03.1', 'return_before_order', 'returns', 'chronology_difference', ZERO, True),
        ('V03.2', 'returned_quantity_above_purchased', 'pairs', 'quantity_difference', ZERO, True),
        ('V03.2', 'refund_above_gross_purchased', 'pairs', 'gross_purchased_difference', TOLERANCE, True),
        ('V03.2', 'refund_above_net_purchased', 'pairs', 'net_purchased_difference', TOLERANCE, True),
        ('V03.3', 'refund_vs_gross_return_value', 'pairs', 'gross_refund_difference', TOLERANCE, False),
        ('V03.3', 'refund_vs_proportional_net_return_value', 'pairs', 'net_refund_difference', TOLERANCE, False),
        ('V03.3', 'refund_above_gross_return_value', 'pairs', 'gross_refund_difference', TOLERANCE, True),
        ('V03.3', 'refund_above_net_return_value', 'pairs', 'net_refund_difference', TOLERANCE, True),
        ('V03.1', 'refund_above_payment', 'orders', 'payment_difference', TOLERANCE, True),
    ]
    QUANTILES = [('p01', .01), ('p05', .05), ('p25', .25), ('p50', .5), ('p75', .75), ('p95', .95), ('p99', .99)]
    RATIO_BUCKETS = ['below_85_percent', '85_to_90_percent', '90_to_95_percent',
                     '95_to_100_percent', 'above_100_percent', 'undefined']


    def ratio_bucket(value):
        if value is None or pd.isna(value):
            return 'undefined'
        for upper, label in [(Decimal('.85'), 'below_85_percent'), (Decimal('.90'), '85_to_90_percent'),
                             (Decimal('.95'), '90_to_95_percent')]:
            if value < upper:
                return label
        return '95_to_100_percent' if value <= 1 else 'above_100_percent'


    def equivalent(left, right):
        """Exact money/count comparison; absolute 1e-12 only for floating statistics."""
        if isinstance(left, dict) and isinstance(right, dict):
            return left.keys() == right.keys() and all(equivalent(left[k], right[k]) for k in left)
        if isinstance(left, list) and isinstance(right, list):
            return len(left) == len(right) and all(equivalent(a, b) for a, b in zip(left, right))
        if left is None or right is None:
            return left is right
        if isinstance(left, float) or isinstance(right, float):
            return math.isclose(float(left), float(right), rel_tol=0, abs_tol=1e-12)
        return left == right


    def ratio_analysis(pairs):
        rows, bins = [], []
        masks = [('all', pd.Series(True, index=pairs.index)), ('discounted', pairs.discount.gt(0)),
                 ('no_discount', pairs.discount.eq(0)), ('negative_discount', pairs.discount.lt(0))]
        for name, mask in masks:
            group = pairs.loc[mask]
            values = group.refund_ratio.dropna().map(float).astype(float)
            row = dict(group=name, count=len(values), missing_count=len(group) - len(values),
                       min=float(values.min()) if len(values) else None,
                       max=float(values.max()) if len(values) else None,
                       mean=float(values.mean()) if len(values) else None,
                       median=float(values.median()) if len(values) else None)
            row.update({label: float(values.quantile(q)) if len(values) else None for label, q in QUANTILES})
            rows.append(row)
            counts = group.refund_ratio.map(ratio_bucket).value_counts()
            bins.extend(dict(group=name, bucket=bucket, pairs=int(counts.get(bucket, 0))) for bucket in RATIO_BUCKETS)
        valid = pairs[['refund_ratio', 'discount_rate']].dropna().astype(float)
        usable = len(valid) > 1 and valid.refund_ratio.nunique() > 1 and valid.discount_rate.nunique() > 1
        correlation = float(valid.refund_ratio.corr(valid.discount_rate)) if usable else None
        return pd.DataFrame(rows), pd.DataFrame(bins), correlation, len(valid)


    def read_sources(paths):
        result = {}
        for name, path in paths.items():
            frame = read_table(path)
            if name in NUMERIC:
                exact = pd.read_csv(path, encoding='utf-8-sig', usecols=NUMERIC[name], dtype='string',
                                    skip_blank_lines=False)
                for column in NUMERIC[name]:
                    frame[column] = exact[column]
            result[name] = frame
        return result


    def canonical(value):
        if value is None or pd.isna(value):
            return None
        return format(value.normalize(), 'f') if isinstance(value, Decimal) else str(value)


    def fingerprint(records, columns, keys):
        """Serialization shared by both implementations; no financial calculations."""
        result = hashlib.sha256()
        for record in sorted(records, key=lambda r: tuple(str(r[k]) for k in keys)):
            result.update((repr([canonical(record[c]) for c in columns]) + '\n').encode('utf-8'))
        return result.hexdigest()


    def lag_bucket(value):
        for upper, label in [(-1, 'before_order'), (0, 'same_day'), (7, '1_to_7'),
                             (14, '8_to_14'), (21, '15_to_21'), (31, '22_to_31')]:
            if value <= upper:
                return label
        return 'over_31'


    def quantity_bucket(value):
        if value < 0:
            return 'negative'
        if value <= 5:
            return str(value.to_integral_value())
        return '6_to_10' if value <= 10 else 'over_10'


    def financial_difference(actual, expected):
        return actual - expected if pd.notna(actual) and pd.notna(expected) else None


    def analyze(returns, orders, order_items, payments):
        """Scan/validate every input row; join aggregated children at their true grain."""
        frames = {name: frame[COLUMNS[name]].copy() for name, frame in
                  zip(COLUMNS, [returns, orders, order_items, payments])}
        r, o, i, p = (frames[n] for n in COLUMNS)
        if o.empty or i.empty or p.empty:
            raise ValueError('orders, order_items and payments must be non-empty')
        key_rows = [require_key(o, 'order_id', 'orders'), require_key(r, 'return_id', 'returns')]
        quality = [dict(table=name, column=column, rows=len(frame), null_count=int(frame[column].isna().sum()))
                   for name, frame in frames.items() for column in COLUMNS[name]]
        links = [require_link(r, o, 'order_id', 'returns -> orders'),
                 require_link(i, o, 'order_id', 'order_items -> orders'),
                 require_link(p, o, 'order_id', 'payments -> orders')]
        for name in ['returns', 'order_items']:
            if frames[name].product_id.isna().any():
                raise ValueError(f'{name}.product_id contains NULL; join refused')
        for name, columns in NUMERIC.items():
            for column in columns:
                frames[name][column] = frames[name][column].map(decimal_value)
        for frame, column in [(r, 'return_quantity'), (i, 'quantity')]:
            if any(v != v.to_integral_value() for v in frame[column]):
                raise ValueError(f'{column}: fractional quantities cannot be interpreted as unit counts')
        o['order_date'] = dates(o.order_date, 'orders.order_date')
        r['return_date'] = dates(r.return_date, 'returns.return_date')
        item_keys = i[PAIR].drop_duplicates()
        pair_link = r[PAIR].merge(item_keys, on=PAIR, how='left', validate='many_to_one', indicator=True)
        orphan_pairs = int(pair_link._merge.eq('left_only').sum())
        if orphan_pairs:
            raise ValueError(f'returns -> order_items: {orphan_pairs} orphan pair rows; join refused')
        links.append(dict(relation='returns -> order_items pairs', child_rows=len(r), null_keys=0,
                          orphan_rows=orphan_pairs))
        presence = o.copy()
        presence['has_return'] = o.order_id.isin(r.order_id)
        presence['presence_difference'] = (o.order_status.eq('returned').fillna(False) & ~presence.has_return).astype(int)
        last_return = r.return_date.max() if len(r) else None
        presence['days_to_last_return'] = ((pd.Timestamp(last_return) - pd.to_datetime(o.order_date)).dt.days
                                           if last_return is not None else None)
        detail = r.merge(o, on='order_id', how='left', validate='many_to_one')
        detail['lag_days'] = (pd.to_datetime(detail.return_date) - pd.to_datetime(detail.order_date)).dt.days
        detail['status_difference'] = (~detail.order_status.eq('returned').fillna(False)).astype(int)
        detail['chronology_difference'] = -detail.lag_days
        # Validate the entire items table above. Select only pairs under examination
        # after the scan; unrelated items cannot contribute to a return-pair formula.
        i['gross'] = i.quantity * i.unit_price
        return_keys = r[PAIR].drop_duplicates()
        relevant = i.merge(return_keys, on=PAIR, how='inner', validate='many_to_one')
        bought = relevant.groupby(PAIR, sort=False).agg(
            purchased_quantity=('quantity', 'sum'), gross=('gross', 'sum'),
            discount=('discount_amount', 'sum'), item_rows=('quantity', 'size'),
            min_price=('unit_price', 'min'), max_price=('unit_price', 'max')).reset_index()
        returned = r.groupby(PAIR, sort=False).agg(
            returned_quantity=('return_quantity', 'sum'), refund=('refund_amount', 'sum'),
            return_rows=('return_id', 'size')).reset_index()
        pairs = returned.merge(bought, on=PAIR, how='left', validate='one_to_one')
        pairs['quantity_difference'] = pairs.returned_quantity - pairs.purchased_quantity
        pairs['net_purchased'] = pairs.gross - pairs.discount
        pairs['gross_purchased_difference'] = pairs.refund - pairs.gross
        pairs['net_purchased_difference'] = pairs.refund - pairs.net_purchased
        pairs['expected_gross_refund'] = [q * g / n if n > 0 else None for q, g, n in
                                          zip(pairs.returned_quantity, pairs.gross, pairs.purchased_quantity)]
        pairs['expected_net_refund'] = [q * (g - d) / n if n > 0 else None for q, g, d, n in
                                        zip(pairs.returned_quantity, pairs.gross, pairs.discount, pairs.purchased_quantity)]
        for label in ['gross', 'net']:
            pairs[label + '_refund_difference'] = [financial_difference(a, b) for a, b in
                                                   zip(pairs.refund, pairs['expected_' + label + '_refund'])]
        pairs['refund_ratio'] = [a / b if b is not None and b > 0 else None
                                 for a, b in zip(pairs.refund, pairs.expected_gross_refund)]
        pairs['discount_rate'] = [a / b if b > 0 else None for a, b in zip(pairs.discount, pairs.gross)]
        ratio_stats, ratio_distribution, correlation, correlation_cases = ratio_analysis(pairs)
        refund_orders = r.groupby('order_id', sort=False).agg(
            refund=('refund_amount', 'sum'), return_rows=('return_id', 'size'),
            returned_quantity=('return_quantity', 'sum')).reset_index()
        relevant_payments = p[p.order_id.isin(refund_orders.order_id)]
        paid = relevant_payments.groupby('order_id', sort=False).payment_value.sum().rename('payment')
        order_detail = refund_orders.merge(paid, on='order_id', how='left', validate='one_to_one')
        order_detail = order_detail.merge(o, on='order_id', how='left', validate='one_to_one')
        order_detail['payment_difference'] = [financial_difference(a, b) for a, b in
                                              zip(order_detail.refund, order_detail.payment)]
        metrics = dict(returns_rows=len(r), orders_rows=len(o), order_items_rows=len(i), payments_rows=len(p),
                       return_pairs=len(pairs), return_orders=len(order_detail), item_pairs=len(item_keys),
                       duplicate_return_pairs_excess=len(r) - len(pairs),
                       duplicate_item_pairs_excess=len(i) - len(item_keys),
                       repeated_return_pairs=int(pairs.return_rows.gt(1).sum()),
                       item_rows_in_return_pairs=len(relevant), payment_rows_in_return_orders=len(relevant_payments),
                       returned_quantity=sum(r.return_quantity, ZERO), refund=sum(r.refund_amount, ZERO),
                       all_item_quantity=sum(i.quantity, ZERO), all_item_gross=sum(i.gross, ZERO),
                       all_item_discount=sum(i.discount_amount, ZERO), all_payment=sum(p.payment_value, ZERO),
                       returned_orders_without_returns=int(presence.presence_difference.sum()),
                       returns_on_nonreturned_status=int(detail.status_difference.sum()),
                       return_before_order=int(detail.lag_days.lt(0).sum()),
                       nonpositive_return_quantity=int(r.return_quantity.le(0).sum()),
                       nonpositive_item_quantity=int(i.quantity.le(0).sum()),
                       negative_refund_rows=int(r.refund_amount.lt(0).sum()),
                       nonpositive_purchased_pairs=int(pairs.purchased_quantity.le(0).sum()),
                       ambiguous_price_pairs=int(pairs.min_price.ne(pairs.max_price).sum()),
                       return_orders_without_payment=int(order_detail.payment.isna().sum()),
                       orders_with_multiple_returns=int(order_detail.return_rows.gt(1).sum()),
                       full_return_pairs=int(pairs.returned_quantity.eq(pairs.purchased_quantity).sum()),
                       partial_return_pairs=int((pairs.returned_quantity.gt(0) & pairs.returned_quantity.lt(pairs.purchased_quantity)).sum()),
                       over_return_pairs=int(pairs.quantity_difference.gt(0).sum()),
                       refund_matches_gross_return=int(pairs.gross_refund_difference.dropna().abs().le(TOLERANCE).sum()),
                       refund_matches_net_return=int(pairs.net_refund_difference.dropna().abs().le(TOLERANCE).sum()),
                       refund_above_gross_return=int(pairs.gross_refund_difference.dropna().gt(TOLERANCE).sum()),
                       refund_above_net_return=int(pairs.net_refund_difference.dropna().gt(TOLERANCE).sum()),
                       refund_above_gross_purchased=int(pairs.gross_purchased_difference.gt(TOLERANCE).sum()),
                       refund_above_net_purchased=int(pairs.net_purchased_difference.gt(TOLERANCE).sum()),
                       refund_orders_above_payment=int(order_detail.payment_difference.dropna().gt(TOLERANCE).sum()),
                       refund_ratio_mean=float(ratio_stats.iloc[0]['mean']) if len(pairs.refund_ratio.dropna()) else None,
                       refund_ratio_min=float(ratio_stats.iloc[0]['min']) if len(pairs.refund_ratio.dropna()) else None,
                       refund_ratio_max=float(ratio_stats.iloc[0]['max']) if len(pairs.refund_ratio.dropna()) else None,
                       pearson_refund_ratio_discount_rate=correlation, pearson_cases=correlation_cases,
                       lag_median_days=float(detail.lag_days.median()) if len(detail) else None,
                       lag_min_days=int(detail.lag_days.min()) if len(detail) else None,
                       lag_max_days=int(detail.lag_days.max()) if len(detail) else None,
                       lag_sum_days=int(detail.lag_days.sum()))
        metrics['lag_mean_days'] = Decimal(metrics['lag_sum_days']) / len(r) if len(r) else None
        missing = presence[presence.presence_difference.eq(1)]
        gap = missing.days_to_last_return.dropna()
        cutoff = dict(last_return_date=last_return, last_order_date=o.order_date.max(), missing_detail_orders=len(missing),
                      first_missing_order_date=missing.order_date.min() if len(missing) else None,
                      last_missing_order_date=missing.order_date.max() if len(missing) else None,
                      min_days_to_last_return=int(gap.min()) if len(gap) else None,
                      max_days_to_last_return=int(gap.max()) if len(gap) else None,
                      mean_days_to_last_return=float(gap.mean()) if len(gap) else None,
                      missing_after_last_return=int(gap.lt(0).sum()),
                      missing_within_observed_max_lag=int(gap.between(0, metrics['lag_max_days']).sum()) if len(gap) else 0)
        missing_dates = missing.groupby('order_date').size().rename('orders').reset_index()
        missing_months = missing.assign(order_month=missing.order_date.str[:7]).groupby('order_month').size().rename('orders').reset_index()
        status = presence.groupby(['order_status', 'has_return'], dropna=False).size().rename('orders').reset_index()
        reasons = r.groupby('return_reason', dropna=False).agg(
            return_rows=('return_id', 'size'), returned_quantity=('return_quantity', 'sum'),
            refund=('refund_amount', 'sum')).reset_index().sort_values('return_rows', ascending=False, kind='stable')
        lag_counts = detail.lag_days.map(lag_bucket).value_counts().sort_index().rename_axis('bucket').reset_index(name='return_rows')
        quantity_counts = r.return_quantity.map(quantity_bucket).value_counts().sort_index().rename_axis('bucket').reset_index(name='return_rows')
        ledgers = dict(returns=detail, pairs=pairs, orders=order_detail, presence=presence)
        fingerprints = {
            'returns': fingerprint(detail.to_dict('records'), RETURN_FIELDS, ['return_id']),
            'pairs': fingerprint(pairs.to_dict('records'), PAIR_FIELDS, PAIR),
            'orders': fingerprint(order_detail.to_dict('records'), ORDER_FIELDS, ['order_id']),
            'status_presence': fingerprint(presence.to_dict('records'), PRESENCE_FIELDS, ['order_id'])}
        checks = dict(input_keys_and_foreign_keys_valid=True, return_join_preserves_rows=len(detail) == len(r),
                      pair_join_preserves_rows=len(pairs) == len(returned),
                      order_join_preserves_rows=len(order_detail) == r.order_id.nunique(),
                      status_distribution_covers_all_orders=int(status.orders.sum()) == len(o),
                      reason_distribution_covers_all_returns=int(reasons.return_rows.sum()) == len(r))
        distributions = dict(status_presence=status, return_reasons=reasons,
                             return_lag_days=lag_counts, return_quantities=quantity_counts,
                             key_integrity=pd.DataFrame(key_rows), foreign_keys=pd.DataFrame(links),
                             input_validation=pd.DataFrame(quality),
                             refund_ratio_statistics=ratio_stats, refund_ratio_distribution=ratio_distribution,
                             cutoff_summary=pd.DataFrame([cutoff]), missing_return_order_dates=missing_dates,
                             missing_return_order_months=missing_months)
        return metrics, checks, ledgers, distributions, fingerprints


    def summarize(section, name, differences, tolerance, one_sided):
        valid = [decimal_value(v) for v in differences if pd.notna(v)]
        over = sum(v > tolerance if one_sided else abs(v) > tolerance for v in valid)
        missing = len(differences) - len(valid)
        absolute = [abs(v) for v in valid]
        return dict(section=section, comparison=name, cases=len(differences), compared_cases=len(valid),
                    missing_cases=missing, exact_zero_cases=sum(v == 0 for v in valid),
                    matched_cases=len(valid) - over, mismatched_cases=over + missing,
                    beyond_threshold_count=over, positive_difference_cases=sum(v > 0 for v in valid),
                    negative_difference_cases=sum(v < 0 for v in valid),
                    below_tolerance_count=sum(v < -tolerance for v in valid),
                    above_tolerance_count=sum(v > tolerance for v in valid),
                    within_tolerance_count=sum(abs(v) <= tolerance for v in valid),
                    min_signed_difference=min(valid, default=None), max_signed_difference=max(valid, default=None),
                    max_abs_difference=max(absolute, default=None), sum_signed_difference=sum(valid, ZERO),
                    mean_abs_difference=sum(absolute, ZERO) / len(valid) if valid else None,
                    tolerance=tolerance, direction='upper_bound' if one_sided else 'absolute_difference')


    def compact_reports(metrics, ledgers, distributions, examples=20):
        if not 1 <= examples <= 20:
            raise ValueError('examples must be between 1 and 20')
        reports = dict(distributions)
        summaries, exceptions = [], {}
        for section, name, grain, column, tolerance, one_sided in DEFINITIONS:
            frame = ledgers[grain]
            values = frame[column]
            row = summarize(section, name, values.tolist(), tolerance, one_sided)
            bad = values.map(lambda v: pd.isna(v) or (v > tolerance if one_sided else abs(v) > tolerance))
            selected = frame.loc[bad].copy()
            # Sort identifiers, preserving codes and deterministic examples; never export full ledgers.
            keys = PAIR if grain == 'pairs' else ['return_id'] if grain == 'returns' else ['order_id']
            selected = selected.sort_values(keys, kind='stable').head(examples)
            if grain == 'pairs':
                common = [*PAIR, 'return_rows', 'item_rows', 'returned_quantity', 'purchased_quantity', 'refund']
                relevant = {'quantity_difference': [], 'gross_purchased_difference': ['gross'],
                            'net_purchased_difference': ['gross', 'discount', 'net_purchased'],
                            'gross_refund_difference': ['gross', 'expected_gross_refund'],
                            'net_refund_difference': ['gross', 'discount', 'expected_net_refund']}[column]
                selected = selected[[*common, *relevant, column]]
            elif grain == 'presence':
                selected = selected[['order_id', 'order_date', 'order_status', 'days_to_last_return']]
            elif grain == 'returns':
                selected = selected[['return_id', 'order_id', 'product_id', 'order_status',
                                      'order_date', 'return_date', 'lag_days', column]]
            row.update(examples_reported=len(selected), examples_omitted=row['mismatched_cases'] - len(selected))
            summaries.append(row)
            exceptions[name] = selected
        reports['comparisons'] = pd.DataFrame(summaries)
        reports['repeated_return_pair_examples'] = ledgers['pairs'].loc[
            ledgers['pairs'].return_rows.gt(1)].sort_values(PAIR).head(examples)
        reports['ambiguous_price_pair_examples'] = ledgers['pairs'].loc[
            ledgers['pairs'].min_price.ne(ledgers['pairs'].max_price),
            [*PAIR, 'item_rows', 'min_price', 'max_price', 'gross', 'purchased_quantity']].sort_values(PAIR).head(examples)
        # Reasons are data labels, potentially high cardinality. Keep full totals separately.
        reasons = reports['return_reasons']
        reports['return_reason_coverage'] = pd.DataFrame([dict(
            categories=len(reasons), categories_reported=min(len(reasons), 20),
            omitted_return_rows=int(reasons.iloc[20:].return_rows.sum()))])
        reports['return_reasons'] = reasons.head(20)
        return reports, exceptions
    return SimpleNamespace(
        argparse=argparse,
        csv=csv,
        hashlib=hashlib,
        math=math,
        statistics=statistics,
        sys=sys,
        Counter=Counter,
        defaultdict=defaultdict,
        datetime=datetime,
        timezone=timezone,
        Decimal=Decimal,
        Path=Path,
        pd=pd,
        ZERO=ZERO,
        TOLERANCE=TOLERANCE,
        dates=dates,
        decimal_value=decimal_value,
        digest=digest,
        require_key=require_key,
        require_link=require_link,
        NA_TOKENS=NA_TOKENS,
        read_table=read_table,
        ROOT=ROOT,
        PAIR=PAIR,
        COLUMNS=COLUMNS,
        NUMERIC=NUMERIC,
        PAIR_FIELDS=PAIR_FIELDS,
        ORDER_FIELDS=ORDER_FIELDS,
        RETURN_FIELDS=RETURN_FIELDS,
        PRESENCE_FIELDS=PRESENCE_FIELDS,
        SECTIONS=SECTIONS,
        DEFINITIONS=DEFINITIONS,
        QUANTILES=QUANTILES,
        RATIO_BUCKETS=RATIO_BUCKETS,
        ratio_bucket=ratio_bucket,
        equivalent=equivalent,
        ratio_analysis=ratio_analysis,
        read_sources=read_sources,
        canonical=canonical,
        fingerprint=fingerprint,
        lag_bucket=lag_bucket,
        quantity_bucket=quantity_bucket,
        financial_difference=financial_difference,
        analyze=analyze,
        summarize=summarize,
        compact_reports=compact_reports,
    )


@cache
def v04():
    """V04: monthly inventory vs transactions, with explicit unmatched-pair coverage."""

    import argparse
    import calendar
    import csv
    import math
    import statistics
    import sys
    from collections import Counter, defaultdict
    from datetime import datetime, timezone
    from decimal import Decimal
    from pathlib import Path

    import pandas as pd

    dates = v02().dates
    decimal_value = v02().decimal_value
    digest = v02().digest
    require_key = v02().require_key
    require_link = v02().require_link
    fingerprint = v03().fingerprint
    NA_TOKENS = source_profiles().NA_TOKENS
    read_table = table_reader().read_table


    ROOT = PROJECT_ROOT
    PAIR = ['product_id', 'month']
    COLUMNS = {'inventory': ['snapshot_date', 'product_id', 'year', 'month', 'units_sold'],
               'orders': ['order_id', 'order_date', 'order_status'],
               'order_items': ['order_id', 'product_id', 'quantity']}
    NUMERIC = {'inventory': ['year', 'month', 'units_sold'], 'order_items': ['quantity']}
    LEDGER_COLUMNS = [*PAIR, 'inventory_units', 'transaction_value', 'coverage', 'difference']


    def equivalent(a, b):
        if isinstance(a, dict) and isinstance(b, dict):
            return a.keys() == b.keys() and all(equivalent(a[k], b[k]) for k in a)
        if isinstance(a, list) and isinstance(b, list):
            return len(a) == len(b) and all(equivalent(x, y) for x, y in zip(a, b))
        if a is None or b is None:
            return a is b
        if isinstance(a, float) or isinstance(b, float):
            return math.isclose(float(a), float(b), rel_tol=0, abs_tol=1e-9)
        return a == b


    def integer_values(series, name):
        values = series.map(decimal_value)
        if any(v != v.to_integral_value() or not -(2 ** 63) <= v < 2 ** 63 for v in values):
            raise ValueError(f'{name}: finite int64 whole-unit values required')
        return values.map(int).astype('int64')


    def read_sources(paths):
        frames = {}
        for name, path in paths.items():
            frame = read_table(path)
            if name in NUMERIC:
                exact = pd.read_csv(path, encoding='utf-8-sig', usecols=NUMERIC[name], dtype='string')
                for column in NUMERIC[name]:
                    frame[column] = exact[column]
            frames[name] = frame
        return frames


    def measure_names(statuses):
        return [dict(metric='quantity', definition='SUM(quantity), all order statuses', status=None),
                dict(metric='item_rows', definition='Number of item rows, without deduplication', status=None),
                dict(metric='distinct_orders', definition='COUNT(DISTINCT order_id)', status=None),
                *[dict(metric=f'status_quantity_{n}', definition='SUM(quantity) restricted to this observed status; diagnostic only',
                       status=status) for n, status in enumerate(statuses)]]


    def compare_measure(inventory, transactions, metric):
        # A status absent from a transaction pair remains absent, never an imputed zero.
        selected = transactions.loc[transactions[metric].notna(), [*PAIR, metric]].rename(columns={metric: 'transaction_value'})
        ledger = inventory[[*PAIR, 'units_sold']].rename(columns={'units_sold': 'inventory_units'}).merge(
            selected, on=PAIR, how='outer', validate='one_to_one', indicator=True).sort_values(PAIR).reset_index(drop=True)
        for column in ['inventory_units', 'transaction_value']:
            ledger[column] = ledger[column].astype('Int64')
        ledger['coverage'] = ledger.pop('_merge').map({'left_only': 'inventory_only', 'right_only': 'transactions_only', 'both': 'both'}).astype(str)
        ledger['difference'] = ledger.inventory_units - ledger.transaction_value
        ledger['absolute_difference'] = ledger.difference.abs()
        valid_denominator = ledger.coverage.eq('both') & ledger.transaction_value.ne(0).fillna(False)
        ledger['relative_difference'] = pd.Series(pd.NA, index=ledger.index, dtype='Float64')
        ledger.loc[valid_denominator, 'relative_difference'] = (
            ledger.loc[valid_denominator, 'difference'] / ledger.loc[valid_denominator, 'transaction_value'])
        ledger['absolute_relative_difference'] = ledger.relative_difference.abs()
        return ledger


    def summarize(ledger, metric):
        both = ledger[ledger.coverage.eq('both')]
        difference = both.difference.astype('int64')
        absolute = difference.abs()
        relative = both.relative_difference.dropna().astype(float)
        absolute_relative = both.absolute_relative_difference.dropna().astype(float)
        usable = len(both) > 1 and both.inventory_units.nunique() > 1 and both.transaction_value.nunique() > 1
        total_abs_transactions = int(both.transaction_value.abs().sum())
        row = dict(metric=metric, union_pairs=len(ledger), both_pairs=len(both),
                   inventory_only_pairs=int(ledger.coverage.eq('inventory_only').sum()),
                   transactions_only_pairs=int(ledger.coverage.eq('transactions_only').sum()),
                   equal_pairs=int(difference.eq(0).sum()), inventory_greater_pairs=int(difference.gt(0).sum()),
                   inventory_lower_pairs=int(difference.lt(0).sum()),
                   inventory_total_on_both=int(both.inventory_units.sum()), transaction_total_on_both=int(both.transaction_value.sum()),
                   min_signed_difference=int(difference.min()) if len(both) else None,
                   max_signed_difference=int(difference.max()) if len(both) else None,
                   mean_signed_difference=float(difference.mean()) if len(both) else None,
                   mean_absolute_difference=float(absolute.mean()) if len(both) else None,
                   max_absolute_difference=int(absolute.max()) if len(both) else None,
                   pearson=float(both.inventory_units.astype(float).corr(both.transaction_value.astype(float))) if usable else None,
                   relative_compared_pairs=len(relative), relative_undefined_zero_denominator=int(both.transaction_value.eq(0).sum()),
                   mean_relative_difference=float(relative.mean()) if len(relative) else None,
                   mean_absolute_relative_difference=float(absolute_relative.mean()) if len(relative) else None,
                   max_absolute_relative_difference=float(absolute_relative.max()) if len(relative) else None,
                   weighted_absolute_relative_difference=int(absolute.sum()) / total_abs_transactions if total_abs_transactions else None)
        row.update({f'absolute_difference_p{q}': float(absolute.quantile(q / 100)) if len(both) else None for q in [50, 90, 95, 99]})
        return row


    def absolute_bucket(value):
        if value == 0:
            return 'equal'
        for limit in [5, 10, 25, 50, 100]:
            if value <= limit:
                return f'abs_le_{limit}'
        return 'abs_gt_100'


    def relative_bucket(value):
        if value is None or pd.isna(value):
            return 'undefined_zero_denominator'
        if value == 0:
            return 'equal'
        for limit, label in [(0.1, 'abs_le_10_percent'), (.25, 'abs_le_25_percent'),
                             (.5, 'abs_le_50_percent'), (1, 'abs_le_100_percent')]:
            if value <= limit:
                return label
        return 'abs_gt_100_percent'


    def analyze(inventory, orders, order_items):
        originals = dict(inventory=inventory, orders=orders, order_items=order_items)
        quality = [dict(table=name, rows=len(frame), columns=len(frame.columns),
                        duplicate_rows=int(frame.duplicated().sum()),
                        required_null_cells=int(frame[COLUMNS[name]].isna().sum().sum()),
                        all_null_cells=int(frame.isna().sum().sum())) for name, frame in originals.items()]
        inv, o, items = (originals[n][COLUMNS[n]].copy() for n in COLUMNS)
        if inv.empty or o.empty or items.empty:
            raise ValueError('All three source tables must be non-empty')
        keys = [require_key(o, 'order_id', 'orders')]
        link = require_link(items, o, 'order_id', 'order_items -> orders')
        if inv.product_id.isna().any() or items.product_id.isna().any():
            raise ValueError('NULL product_id; pair comparison refused')
        inv['snapshot_date'] = dates(inv.snapshot_date, 'inventory.snapshot_date')
        o['order_date'] = dates(o.order_date, 'orders.order_date')
        for column in ['year', 'month', 'units_sold']:
            inv[column] = integer_values(inv[column], 'inventory.' + column)
        items['quantity'] = integer_values(items.quantity, 'order_items.quantity')
        snapshots = pd.to_datetime(inv.snapshot_date)
        year_mismatch = int(inv.year.ne(snapshots.dt.year).sum())
        month_mismatch = int(inv.month.ne(snapshots.dt.month).sum())
        if year_mismatch or month_mismatch:
            raise ValueError(f'Inventory year/month disagree with snapshot_date: year={year_mismatch}, month={month_mismatch}')
        inv['month'] = snapshots.dt.strftime('%Y-%m')
        duplicate_pairs = int(inv.duplicated(PAIR).sum())
        if duplicate_pairs:
            raise ValueError(f'inventory product-month duplicate_excess={duplicate_pairs}; no automatic aggregation')
        keys.append(dict(table='inventory', key='(product_id, YYYY-MM)', rows=len(inv), null_keys=0, duplicate_keys_excess=duplicate_pairs))
        joined = items.merge(o, on='order_id', how='left', validate='many_to_one')
        joined['month'] = joined.order_date.str[:7]
        joined['order_status'] = joined.order_status.astype(object).where(joined.order_status.notna(), None)
        statuses = sorted(o.order_status.astype(object).where(o.order_status.notna(), None).unique(), key=lambda s: '' if s is None else s)
        measures = measure_names(statuses)
        tx = joined.groupby(PAIR).agg(quantity=('quantity', 'sum'), item_rows=('quantity', 'size'),
                                      distinct_orders=('order_id', 'nunique')).reset_index()
        status_rows = []
        for measure in measures[3:]:
            status = measure['status']
            mask = joined.order_status.isna() if status is None else joined.order_status.eq(status)
            subset = joined[mask]
            series = subset.groupby(PAIR).quantity.sum().rename(measure['metric']).reset_index()
            tx = tx.merge(series, on=PAIR, how='left', validate='one_to_one')
            tx[measure['metric']] = tx[measure['metric']].astype('Int64')
            order_mask = o.order_status.isna() if status is None else o.order_status.eq(status)
            status_rows.append(dict(status=status, orders=int(order_mask.sum()), item_rows=len(subset),
                                    quantity=int(subset.quantity.sum()), product_month_pairs=len(series)))
        ledgers = {m['metric']: compare_measure(inv, tx, m['metric']) for m in measures}
        summaries = [dict(summarize(ledgers[m['metric']], m['metric']), definition=m['definition'], status=m['status']) for m in measures]
        primary = ledgers['quantity']
        both = primary[primary.coverage.eq('both')]
        inv_products, tx_products = set(inv.product_id), set(tx.product_id)
        metrics = dict(inventory_rows=len(inv), orders_rows=len(o), order_items_rows=len(items),
                       inventory_pairs=len(inv), transaction_pairs=len(tx), inventory_products=len(inv_products),
                       transaction_products=len(tx_products), common_products=len(inv_products & tx_products),
                       snapshot_month_end_rows=int(snapshots.dt.is_month_end.sum()),
                       year_mismatch_rows=year_mismatch, month_mismatch_rows=month_mismatch,
                       inventory_duplicate_pairs_excess=duplicate_pairs,
                       duplicate_item_order_product_excess=int(items.duplicated(['order_id', 'product_id']).sum()),
                       negative_inventory_units_rows=int(inv.units_sold.lt(0).sum()), negative_transaction_quantity_rows=int(items.quantity.lt(0).sum()),
                       inventory_first_month=inv.month.min(), inventory_last_month=inv.month.max(),
                       transaction_first_month=tx.month.min(), transaction_last_month=tx.month.max(),
                       inventory_units_total=int(inv.units_sold.sum()), transaction_quantity_total=int(items.quantity.sum()),
                       inventory_only_pairs_product_absent_from_transactions=int((primary.coverage.eq('inventory_only') & ~primary.product_id.isin(tx_products)).sum()),
                       transactions_only_pairs_product_absent_from_inventory=int((primary.coverage.eq('transactions_only') & ~primary.product_id.isin(inv_products)).sum()))
        metrics.update({k: v for k, v in summaries[0].items() if k not in ['metric', 'definition', 'status']})
        distributions = {
            'absolute_difference': Counter(absolute_bucket(int(v)) for v in both.absolute_difference),
            'absolute_relative_difference': Counter(relative_bucket(v) for v in both.absolute_relative_difference)}
        coverage_year = primary.assign(year=primary.month.str[:4]).groupby(['year', 'coverage']).size().rename('pairs').reset_index()
        reports = dict(comparisons=pd.DataFrame(summaries), status_totals=pd.DataFrame(status_rows),
                       source_quality=pd.DataFrame(quality), key_integrity=pd.DataFrame(keys), foreign_keys=pd.DataFrame([link]),
                       coverage_by_year=coverage_year,
                       **{name: pd.DataFrame([dict(bucket=k, pairs=v) for k, v in sorted(counts.items())]) for name, counts in distributions.items()})
        fingerprints = dict(inventory=fingerprint(inv.to_dict('records'), [*PAIR, 'snapshot_date', 'units_sold'], PAIR),
                            transactions=fingerprint(tx.to_dict('records'), [*PAIR, *[m['metric'] for m in measures]], PAIR),
                            primary_comparison=fingerprint(primary.to_dict('records'), LEDGER_COLUMNS, PAIR))
        checks = dict(keys_and_order_foreign_key_valid=True, item_join_preserves_rows=len(joined) == len(items),
                      coverage_partitions_union=metrics['union_pairs'] == metrics['both_pairs'] + metrics['inventory_only_pairs'] + metrics['transactions_only_pairs'],
                      equality_partitions_intersection=len(both) == metrics['equal_pairs'] + metrics['inventory_greater_pairs'] + metrics['inventory_lower_pairs'],
                      status_quantity_partitions_all_items=sum(r['quantity'] for r in status_rows) == int(items.quantity.sum()))
        return metrics, checks, ledgers, reports, fingerprints


    def compact_examples(primary, examples):
        if not 1 <= examples <= 20:
            raise ValueError('examples must be between 1 and 20')
        groups = {
            'inventory_only': primary[primary.coverage.eq('inventory_only')],
            'transactions_only': primary[primary.coverage.eq('transactions_only')],
            'largest_absolute_differences': primary[primary.coverage.eq('both') & primary.difference.ne(0).fillna(False)].sort_values(
                ['absolute_difference', *PAIR], ascending=[False, True, True], kind='stable'),
            'inventory_greater': primary[primary.difference.gt(0).fillna(False)].sort_values(['difference', *PAIR], ascending=[False, True, True]),
            'inventory_lower': primary[primary.difference.lt(0).fillna(False)].sort_values(['difference', *PAIR]),
            'largest_relative_differences': primary[primary.absolute_relative_difference.gt(0).fillna(False)].sort_values(
                ['absolute_relative_difference', *PAIR], ascending=[False, True, True])}
        return {n: frame.head(examples) for n, frame in groups.items()}, [
            dict(group=n, cases=len(frame), examples_reported=min(len(frame), examples), examples_omitted=max(0, len(frame) - examples))
            for n, frame in groups.items()]


    def independent_summary(records, metric):
        both = [r for r in records if r['coverage'] == 'both']
        x = [r['inventory_units'] for r in both]
        y = [r['transaction_value'] for r in both]
        differences = [a - b for a, b in zip(x, y)]
        absolute = sorted(map(abs, differences))
        relative = [d / b for d, b in zip(differences, y) if b != 0]
        absolute_relative = list(map(abs, relative))
        correlation = None
        if len(x) > 1:
            mx, my = statistics.fmean(x), statistics.fmean(y)
            xx = math.fsum((v - mx) ** 2 for v in x)
            yy = math.fsum((v - my) ** 2 for v in y)
            if xx and yy:
                correlation = math.fsum((a - mx) * (b - my) for a, b in zip(x, y)) / math.sqrt(xx * yy)
        row = dict(metric=metric, union_pairs=len(records), both_pairs=len(both),
                   inventory_only_pairs=sum(r['coverage'] == 'inventory_only' for r in records),
                   transactions_only_pairs=sum(r['coverage'] == 'transactions_only' for r in records),
                   equal_pairs=sum(v == 0 for v in differences), inventory_greater_pairs=sum(v > 0 for v in differences),
                   inventory_lower_pairs=sum(v < 0 for v in differences), inventory_total_on_both=sum(x), transaction_total_on_both=sum(y),
                   min_signed_difference=min(differences, default=None), max_signed_difference=max(differences, default=None),
                   mean_signed_difference=statistics.fmean(differences) if differences else None,
                   mean_absolute_difference=statistics.fmean(absolute) if absolute else None,
                   max_absolute_difference=max(absolute, default=None), pearson=correlation,
                   relative_compared_pairs=len(relative), relative_undefined_zero_denominator=sum(v == 0 for v in y),
                   mean_relative_difference=statistics.fmean(relative) if relative else None,
                   mean_absolute_relative_difference=statistics.fmean(absolute_relative) if absolute_relative else None,
                   max_absolute_relative_difference=max(absolute_relative, default=None),
                   weighted_absolute_relative_difference=sum(absolute) / sum(map(abs, y)) if any(y) else None)
        for q in [50, 90, 95, 99]:
            position = (len(absolute) - 1) * q / 100
            lo, hi = math.floor(position), math.ceil(position)
            row[f'absolute_difference_p{q}'] = absolute[lo] + (absolute[hi] - absolute[lo]) * (position - lo) if absolute else None
        return row
    return SimpleNamespace(
        argparse=argparse,
        calendar=calendar,
        csv=csv,
        math=math,
        statistics=statistics,
        sys=sys,
        Counter=Counter,
        defaultdict=defaultdict,
        datetime=datetime,
        timezone=timezone,
        Decimal=Decimal,
        Path=Path,
        pd=pd,
        dates=dates,
        decimal_value=decimal_value,
        digest=digest,
        require_key=require_key,
        require_link=require_link,
        fingerprint=fingerprint,
        NA_TOKENS=NA_TOKENS,
        read_table=read_table,
        ROOT=ROOT,
        PAIR=PAIR,
        COLUMNS=COLUMNS,
        NUMERIC=NUMERIC,
        LEDGER_COLUMNS=LEDGER_COLUMNS,
        equivalent=equivalent,
        integer_values=integer_values,
        read_sources=read_sources,
        measure_names=measure_names,
        compare_measure=compare_measure,
        summarize=summarize,
        absolute_bucket=absolute_bucket,
        relative_bucket=relative_bucket,
        analyze=analyze,
        compact_examples=compact_examples,
        independent_summary=independent_summary,
    )


@cache
def v05():
    """V05: observed reorder-flag consistency and target usability, without relabeling."""

    import argparse
    import csv
    import math
    import statistics
    import sys
    from collections import Counter
    from datetime import datetime, timezone
    from decimal import Decimal, InvalidOperation
    from pathlib import Path

    import pandas as pd

    digest = v02().digest
    fingerprint = v03().fingerprint
    equivalent = v04().equivalent
    NA_TOKENS = source_profiles().NA_TOKENS
    read_table = table_reader().read_table


    ROOT = PROJECT_ROOT
    REQUIRED = ['reorder_flag', 'stock_on_hand', 'days_of_supply', 'stockout_flag']
    FEATURES = ['stock_on_hand', 'days_of_supply', 'stockout_flag', 'stockout_days', 'overstock_flag']
    NUMERIC = set(FEATURES + ['reorder_flag', 'units_received', 'units_sold', 'fill_rate',
                              'sell_through_rate', 'year', 'month'])
    BINARY = {'reorder_flag', 'stockout_flag', 'overstock_flag'}
    BUCKETS = ['0', '1', 'NULL', 'invalid']
    GROUPS = ['all_rows', *BUCKETS]
    CONDITIONS = [('days_of_supply_le_30', 'days_of_supply', '<=', Decimal(30)),
                  ('stock_on_hand_le_5', 'stock_on_hand', '<=', Decimal(5)),
                  ('stock_on_hand_le_10', 'stock_on_hand', '<=', Decimal(10)),
                  ('stockout_flag_eq_1', 'stockout_flag', '==', Decimal(1)),
                  ('stockout_days_gt_0', 'stockout_days', '>', Decimal(0)),
                  ('overstock_flag_eq_1', 'overstock_flag', '==', Decimal(1))]


    def read_source(path):
        inferred = read_table(path)  # Reuse structural CSV validation and record inference.
        exact = pd.read_csv(path, encoding='utf-8-sig', dtype='string', skip_blank_lines=False)
        exact.attrs['parsed_dtypes'] = {c: str(t) for c, t in inferred.dtypes.items()}
        return exact


    def number(value):
        if value is None or pd.isna(value) or str(value) in NA_TOKENS:
            return None, 'missing'
        try:
            parsed = Decimal(str(value))
        except InvalidOperation:
            return None, 'non_numeric'
        return (parsed, 'finite') if parsed.is_finite() else (None, 'non_finite')


    def flag_category(value, reason):
        if reason == 'missing':
            return 'NULL'
        return str(int(value)) if reason == 'finite' and value in (0, 1) else 'invalid'


    def domain_valid(column, value):
        if column in BINARY:
            return value in (0, 1)
        if column in {'stock_on_hand', 'stockout_days'}:
            return value >= 0 and value == value.to_integral_value()
        if column == 'days_of_supply':
            return value >= 0
        return True


    def domain_description(column):
        if column in BINARY:
            return 'finite numeric 0 or 1'
        if column in {'stock_on_hand', 'stockout_days'}:
            return 'nonnegative whole units/days (diagnostic expectation)'
        return 'nonnegative finite number' if column == 'days_of_supply' else 'finite numeric' if column in NUMERIC else 'observed text'


    def value_token(raw, parsed, reason):
        if reason == 'missing':
            return None
        return format(parsed.normalize(), 'f') if reason == 'finite' else str(raw)


    def assess(counts, distinct):
        n = sum(counts.values())
        valid = counts['0'] + counts['1']
        classes = int(counts['0'] > 0) + int(counts['1'] > 0)
        entropy = -sum((counts[b] / valid) * math.log2(counts[b] / valid)
                       for b in ['0', '1'] if valid and counts[b]) if valid else None
        return dict(inventory_rows=n, reorder_zero_rows=counts['0'], reorder_one_rows=counts['1'],
                    reorder_null_rows=counts['NULL'], reorder_invalid_rows=counts['invalid'],
                    binary_valid_rows=valid, binary_class_count=classes, observed_non_null_distinct=distinct,
                    is_constant_non_null=bool(n - counts['NULL'] > 0 and distinct == 1),
                    is_constant_complete=bool(n > 0 and counts['NULL'] == 0 and distinct == 1),
                    valid_binary_label_varies=classes == 2,
                    usable_as_two_class_target_as_is=bool(n and classes == 2 and counts['NULL'] == counts['invalid'] == 0),
                    binary_entropy_bits=entropy,
                    majority_class_fraction_valid=max(counts['0'], counts['1']) / valid if valid else None)


    def condition_applies(value, operator, threshold):
        return value <= threshold if operator == '<=' else value == threshold if operator == '==' else value > threshold


    def condition_row(name, selected, rejected, unknown, categories):
        yes = Counter(categories[i] for i in selected)
        no = Counter(categories[i] for i in rejected)
        valid_yes, valid_no = yes['0'] + yes['1'], no['0'] + no['1']
        n = len(categories)
        return dict(condition=name, eligible_predictor_rows=len(selected) + len(rejected), unknown_predictor_rows=unknown,
                    selected_rows=len(selected), not_selected_rows=len(rejected),
                    selected_percent_all=100 * len(selected) / n if n else None,
                    selected_valid_binary_targets=valid_yes, selected_positive_targets=yes['1'],
                    positive_percent_selected_valid_targets=100 * yes['1'] / valid_yes if valid_yes else None,
                    complement_valid_binary_targets=valid_no, complement_positive_targets=no['1'],
                    positive_percent_complement_valid_targets=100 * no['1'] / valid_no if valid_no else None), yes


    def analyze(inventory):
        missing = [c for c in REQUIRED if c not in inventory]
        if missing:
            raise ValueError(f'Missing required inventory columns: {missing}')
        frame = inventory.copy(deep=True).reset_index(drop=True)
        features = [c for c in FEATURES if c in frame]
        parsed = {c: frame[c].map(number).tolist() for c in frame if c in NUMERIC}
        categories = [flag_category(value, reason) for value, reason in parsed['reorder_flag']]
        categories_series = pd.Series(categories, dtype=object)
        counts = Counter(categories)
        flag_tokens = [value_token(raw, *pair) for raw, pair in zip(frame.reorder_flag, parsed['reorder_flag'])]
        distinct = len({t for t in flag_tokens if t is not None})
        metrics = assess(counts, distinct)
        profiles = []
        for column in frame:
            raw = frame[column]
            dtype = frame.attrs.get('parsed_dtypes', {}).get(column, str(raw.dtype))
            if column in parsed:
                pairs = parsed[column]
                tokens = pd.Series([value_token(v, *p) for v, p in zip(raw, pairs)], dtype=object)
                finite = [v for v, reason in pairs if reason == 'finite']
                nulls = sum(reason == 'missing' for _, reason in pairs)
                invalid = sum(reason in {'non_numeric', 'non_finite'} for _, reason in pairs)
                profiles.append(dict(column=column, parsed_dtype=dtype, numeric_expected=True, rows=len(frame),
                                     null_count=nulls, distinct_non_null=int(tokens.nunique(dropna=True)),
                                     finite_numeric_count=len(finite), invalid_numeric_count=invalid,
                                     outside_expected_domain_count=sum(not domain_valid(column, v) for v in finite),
                                     minimum=min(finite, default=None), maximum=max(finite, default=None),
                                     expected_domain=domain_description(column)))
            else:
                text = raw.astype('string')
                profiles.append(dict(column=column, parsed_dtype=dtype, numeric_expected=False, rows=len(frame),
                                     null_count=int(text.isna().sum()), distinct_non_null=int(text.nunique(dropna=True)),
                                     finite_numeric_count=0, invalid_numeric_count=0, outside_expected_domain_count=0,
                                     minimum=str(text.min()) if text.notna().any() else None,
                                     maximum=str(text.max()) if text.notna().any() else None,
                                     expected_domain='observed text'))
        distribution = [dict(reorder_bucket=b, rows=counts[b], percent_all=100 * counts[b] / len(frame) if len(frame) else None) for b in BUCKETS]
        observed = Counter(zip(categories, flag_tokens))
        observed_rows = [dict(reorder_bucket=b, canonical_value=v, rows=n) for (b, v), n in
                         sorted(observed.items(), key=lambda p: (-p[1], p[0][0], str(p[0][1])))[:20]]
        metrics['observed_categories_total'] = len(observed)
        metrics['observed_value_rows_omitted'] = len(frame) - sum(r['rows'] for r in observed_rows)
        conditions, by_condition = [], []
        for name, column, operator, threshold in CONDITIONS:
            if column not in frame:
                continue
            numbers = parsed[column]
            eligible = pd.Series([reason == 'finite' and (domain_valid(column, v) if column in BINARY else True) for v, reason in numbers], dtype=bool)
            selected = pd.Series([bool(ok and condition_applies(v, operator, threshold)) for ok, (v, _) in zip(eligible, numbers)], dtype=bool)
            row, yes = condition_row(name, frame.index[selected].tolist(), frame.index[eligible & ~selected].tolist(), int((~eligible).sum()), categories)
            conditions.append(row)
            metrics[name] = row['selected_rows']
            by_condition.extend(dict(condition=name, reorder_bucket=b, rows=yes[b],
                                     percent_group=100 * yes[b] / row['selected_rows'] if row['selected_rows'] else None) for b in BUCKETS)
        summaries, correlations = [], []
        for feature in features:
            feature_values = pd.Series([float(v) if reason == 'finite' else None for v, reason in parsed[feature]], dtype=float)
            for group in GROUPS:
                mask = pd.Series(True, index=frame.index) if group == 'all_rows' else categories_series.eq(group)
                values = feature_values[mask].dropna()
                summaries.append(dict(feature=feature, reorder_group=group, group_rows=int(mask.sum()), finite_rows=len(values),
                                      unavailable_rows=int(mask.sum()) - len(values),
                                      minimum=float(values.min()) if len(values) else None, maximum=float(values.max()) if len(values) else None,
                                      mean=float(values.mean()) if len(values) else None, median=float(values.median()) if len(values) else None,
                                      p25=float(values.quantile(.25)) if len(values) else None, p75=float(values.quantile(.75)) if len(values) else None))
            eligible = [i for i, (v, reason) in enumerate(parsed[feature]) if categories[i] in {'0', '1'} and reason == 'finite'
                        and (domain_valid(feature, v) if feature in BINARY else True)]
            x = feature_values.iloc[eligible]
            y = pd.Series([int(categories[i]) for i in eligible], dtype=float)
            reason = ('insufficient_pairs' if len(x) < 2 else 'constant_target' if y.nunique() < 2
                      else 'constant_predictor' if x.nunique() < 2 else 'defined')
            correlations.append(dict(feature=feature, paired_rows=len(x), excluded_rows=len(frame) - len(x),
                                      pearson=float(x.reset_index(drop=True).corr(y)) if reason == 'defined' else None, reason=reason))
        records = []
        for index in frame.index:
            record = dict(source_row=index + 2, reorder_bucket=categories[index], canonical_value=flag_tokens[index])
            record.update({c: parsed[c][index][0] for c in features})
            records.append(record)
        columns = ['source_row', 'reorder_bucket', 'canonical_value', *features]
        ledger_hash = fingerprint(records, columns, ['source_row'])
        reports = dict(column_profile=pd.DataFrame(profiles), reorder_distribution=pd.DataFrame(distribution),
                       observed_reorder_values=pd.DataFrame(observed_rows), condition_summary=pd.DataFrame(conditions),
                       reorder_by_condition=pd.DataFrame(by_condition), numeric_summary_by_reorder=pd.DataFrame(summaries),
                       predictor_correlations=pd.DataFrame(correlations))
        return metrics, reports, ledger_hash, records


    def conclusions(metrics):
        return dict(
            verified=dict(constant_complete_column=metrics['is_constant_complete'],
                          observed_binary_target_varies=metrics['valid_binary_label_varies'],
                          technically_usable_as_two_class_target_as_is=metrics['usable_as_two_class_target_as_is'],
                          null_rows=metrics['reorder_null_rows'], invalid_rows=metrics['reorder_invalid_rows']),
            interpretation=('Fewer than two valid binary classes are observed; this sample cannot train/evaluate discrimination between 0 and 1.'
                            if metrics['binary_class_count'] < 2 else
                            'Both binary classes are observed; technical two-class feasibility is separate from label quality and business validation.'),
            business_rule_verified=False,
            inferability='A constant prediction can reproduce a complete constant column, but this identifies no replenishment decision boundary or nonconstant business rule.',
            unverified_hypotheses=['Flag may be inactive, use external criteria, or describe a different workflow; none of these causes is established from this CSV.'])
    return SimpleNamespace(
        argparse=argparse,
        csv=csv,
        math=math,
        statistics=statistics,
        sys=sys,
        Counter=Counter,
        datetime=datetime,
        timezone=timezone,
        Decimal=Decimal,
        InvalidOperation=InvalidOperation,
        Path=Path,
        pd=pd,
        digest=digest,
        fingerprint=fingerprint,
        equivalent=equivalent,
        NA_TOKENS=NA_TOKENS,
        read_table=read_table,
        ROOT=ROOT,
        REQUIRED=REQUIRED,
        FEATURES=FEATURES,
        NUMERIC=NUMERIC,
        BINARY=BINARY,
        BUCKETS=BUCKETS,
        GROUPS=GROUPS,
        CONDITIONS=CONDITIONS,
        read_source=read_source,
        number=number,
        flag_category=flag_category,
        domain_valid=domain_valid,
        domain_description=domain_description,
        value_token=value_token,
        assess=assess,
        condition_applies=condition_applies,
        condition_row=condition_row,
        analyze=analyze,
        conclusions=conclusions,
    )


@cache
def v06():
    """V06: promotion NULLs, references, discounts and program metadata; read-only."""

    import argparse
    import csv
    import hashlib
    import re
    import sys
    from collections import Counter
    from datetime import date, datetime, timezone
    from decimal import Decimal, InvalidOperation
    from pathlib import Path

    import pandas as pd

    digest = v02().digest
    equivalent = v04().equivalent
    NA_TOKENS = source_profiles().NA_TOKENS
    read_table = table_reader().read_table


    ROOT = PROJECT_ROOT
    COLUMNS = {'order_items': ['order_id', 'product_id', 'discount_amount', 'promo_id', 'promo_id_2'],
               'promotions': ['promo_id', 'promo_type', 'applicable_category', 'start_date', 'end_date']}
    SLOTS = ['promo_id', 'promo_id_2']
    PRESENCE = ['no_code', 'only_promo_id', 'only_promo_id_2', 'both_codes']
    DISCOUNTS = ['positive', 'zero', 'negative', 'NULL', 'non_numeric', 'non_finite']
    PROFILE_COLUMNS = ['table', 'column', 'parsed_dtype', 'rows', 'null_count', 'null_percent',
                       'missing_or_empty_count', 'text_null_token_count', 'distinct_non_null']
    FREQUENCY_COLUMNS = ['value', 'rows', 'percent_all']


    def read_sources(paths):
        frames = {}
        for name, path in paths.items():
            inferred = read_table(path)  # Existing CSV structural validation and ID convention.
            exact = pd.read_csv(path, encoding='utf-8-sig', dtype='string', keep_default_na=False,
                                skip_blank_lines=False)
            exact.attrs['parsed_dtypes'] = {c: str(t) for c, t in inferred.dtypes.items()}
            frames[name] = exact
        return frames


    def null_kind(value):
        if value is None or pd.isna(value) or value == '':
            return 'missing_or_empty'
        return 'text_null_token' if str(value) in NA_TOKENS else 'non_null'


    def normalized(series):
        return series.map(lambda v: None if null_kind(v) != 'non_null' else str(v)).astype(object)


    def discount_value(value):
        if null_kind(value) != 'non_null':
            return None, 'NULL'
        try:
            number = Decimal(str(value))
        except InvalidOperation:
            return None, 'non_numeric'
        if not number.is_finite():
            return None, 'non_finite'
        return number, 'positive' if number > 0 else 'negative' if number < 0 else 'zero'


    def strict_dates(series):
        text = normalized(series).astype('string')
        syntax = text.str.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', na=False)
        parsed = pd.to_datetime(text.where(syntax), format='%Y-%m-%d', errors='coerce')
        states = pd.Series(['NULL' if pd.isna(v) else 'valid' if pd.notna(d) else 'invalid'
                            for v, d in zip(text, parsed)], index=series.index)
        return parsed, states


    def hash_row(hasher, fields):
        """Shared evidence serialization only; auditors calculate fields independently."""
        hasher.update((repr(fields) + '\n').encode('utf-8'))


    def decimal_text(value):
        return format(value.normalize(), 'f') if value is not None else None


    def bounded(frame, mask, columns, limit):
        positions = frame.index[mask]
        records = [dict(source_row=int(i) + 2, **{c: None if pd.isna(frame.at[i, c]) else str(frame.at[i, c]) for c in columns})
                   for i in positions[:limit]]
        return dict(cases=len(positions), examples_reported=len(records), examples_omitted=len(positions) - len(records), records=records)


    def frequency(series):
        counts = Counter(series)
        top = sorted(((v, n) for v, n in counts.items() if v is not None), key=lambda p: (-p[1], p[0]))[:20]
        selected = top + ([(None, counts[None])] if counts[None] else [])
        rows = [dict(value=v, rows=n, percent_all=100 * n / len(series)) for v, n in selected]
        return rows, dict(distinct_non_null=sum(v is not None for v in counts),
                          rows_omitted=len(series) - sum(n for _, n in selected), non_null_limit=20)


    def analyze(order_items, promotions, examples=20):
        if not 1 <= examples <= 20:
            raise ValueError('examples must be between 1 and 20')
        frames = {'order_items': order_items.copy(deep=True).reset_index(drop=True),
                  'promotions': promotions.copy(deep=True).reset_index(drop=True)}
        for name, required in COLUMNS.items():
            missing = [c for c in required if c not in frames[name]]
            if missing:
                raise ValueError(f'{name}: missing required columns {missing}')
        items, promos = frames['order_items'], frames['promotions']
        n, p = len(items), len(promos)
        profile = []
        for name, frame in frames.items():
            for column in frame:
                kinds = frame[column].map(null_kind)
                nulls = int(kinds.ne('non_null').sum())
                profile.append(dict(table=name, column=column,
                                    parsed_dtype=frame.attrs.get('parsed_dtypes', {}).get(column, str(frame[column].dtype)),
                                    rows=len(frame), null_count=nulls, null_percent=100 * nulls / len(frame) if len(frame) else None,
                                    missing_or_empty_count=int(kinds.eq('missing_or_empty').sum()),
                                    text_null_token_count=int(kinds.eq('text_null_token').sum()),
                                    distinct_non_null=int(normalized(frame[column]).nunique(dropna=True))))
        null_summary = [{k: v for k, v in row.items() if k != 'parsed_dtype'} for row in profile
                        if (row['table'] == 'order_items' and row['column'] in SLOTS)
                        or (row['table'] == 'promotions' and row['column'] == 'applicable_category')]
        null_tokens = []
        for row in null_summary:
            series = frames[row['table']][row['column']]
            counts = Counter(str(v) for v in series if null_kind(v) == 'text_null_token')
            null_tokens.extend(dict(table=row['table'], column=row['column'], token=v, rows=count)
                               for v, count in sorted(counts.items()))
        keys = normalized(promos.promo_id)
        code_set = set(keys.dropna())
        a, b = normalized(items.promo_id), normalized(items.promo_id_2)
        present = a.notna() | b.notna()
        groups = pd.Series(['both_codes' if x and y else 'only_promo_id' if x else 'only_promo_id_2' if y else 'no_code'
                            for x, y in zip(a.notna(), b.notna())], dtype=object)
        counts = Counter(groups)
        duplicate = keys.notna() & keys.duplicated(keep=False)
        metrics = dict(order_items_rows=n, promotions_rows=p, promotion_distinct_codes=len(code_set),
                       promotion_null_key_rows=int(keys.isna().sum()),
                       promotion_duplicate_key_excess=int(keys.dropna().duplicated().sum()),
                       promotion_duplicate_key_rows=int(duplicate.sum()),
                       promotion_duplicate_codes=int(keys[duplicate].nunique()),
                       promotion_keys_unique_non_null=bool(keys.notna().all() and not duplicate.any()),
                       **{g + '_rows': counts[g] for g in PRESENCE})
        for row in null_summary:
            metrics[row['column'] + '_null'] = row['null_count']
        metrics['three_fields_null_total'] = sum(r['null_count'] for r in null_summary)
        refs, unknown_masks = [], {}
        for slot, series in [('promo_id', a), ('promo_id_2', b)]:
            unknown = series.notna() & ~series.isin(code_set)
            unknown_masks[slot] = unknown
            refs.append(dict(slot=slot, non_null_uses=int(series.notna().sum()), distinct_used_codes=int(series.nunique()),
                             known_reference_uses=int((series.notna() & ~unknown).sum()), unknown_reference_uses=int(unknown.sum()),
                             distinct_unknown_codes=int(series[unknown].nunique())))
        same = a.notna() & b.notna() & a.eq(b)
        used = set(a.dropna()) | set(b.dropna())
        metrics.update(non_null_reference_uses_total=sum(r['non_null_uses'] for r in refs),
                       unknown_reference_uses_total=sum(r['unknown_reference_uses'] for r in refs),
                       distinct_used_codes_union=len(used), distinct_unknown_codes_union=len(used - code_set),
                       unused_promotion_codes=len(code_set - used), same_code_both_slots_rows=int(same.sum()))
        amounts = items.discount_amount.map(discount_value).tolist()
        states = pd.Series([state for _, state in amounts], dtype=object)
        finite = [v for v, state in amounts if state in {'positive', 'zero', 'negative'}]
        metrics.update(discount_finite_rows=len(finite), discount_sum=sum(finite, Decimal(0)),
                       discount_min=min(finite, default=None), discount_max=max(finite, default=None))
        for state in DISCOUNTS:
            metrics['discount_' + state + '_rows'] = int(states.eq(state).sum())
        discount_cross = []
        for code_present in [False, True]:
            mask = present.eq(code_present)
            total = int(mask.sum())
            for state in DISCOUNTS:
                count = int((mask & states.eq(state)).sum())
                discount_cross.append(dict(code_presence='has_code' if code_present else 'no_code', discount_state=state,
                                           rows=count, percent_presence_group=100 * count / total if total else None))
                if state in {'positive', 'zero'}:
                    metrics[('has_code' if code_present else 'no_code') + '_discount_' + state + '_rows'] = count
        type_counts, type_coverage = frequency(normalized(promos.promo_type))
        category_counts, category_coverage = frequency(normalized(promos.applicable_category))
        start, start_states = strict_dates(promos.start_date)
        end, end_states = strict_dates(promos.end_date)
        both_valid = start_states.eq('valid') & end_states.eq('valid')
        reversed_dates = both_valid & start.gt(end)
        duration = pd.Series([(end.at[i].date() - start.at[i].date()).days
                              for i in promos.index[both_valid & ~reversed_dates]], dtype='int64')
        date_rows = []
        for column, values, statuses in [('start_date', start, start_states), ('end_date', end, end_states)]:
            date_rows.append(dict(column=column, null_rows=int(statuses.eq('NULL').sum()), invalid_non_null_rows=int(statuses.eq('invalid').sum()),
                                  valid_rows=int(statuses.eq('valid').sum()),
                                  minimum=values.min().date().isoformat() if values.notna().any() else None,
                                  maximum=values.max().date().isoformat() if values.notna().any() else None))
        metrics.update(valid_date_pair_rows=int(both_valid.sum()), reversed_date_intervals=int(reversed_dates.sum()),
                       duration_eligible_rows=len(duration), duration_excluded_rows=p - len(duration))
        duration_summary = dict(eligible_rows=len(duration), excluded_rows=p - len(duration),
                                minimum=int(duration.min()) if len(duration) else None, maximum=int(duration.max()) if len(duration) else None,
                                mean=float(duration.mean()) if len(duration) else None, median=float(duration.median()) if len(duration) else None,
                                p25=float(duration.quantile(.25)) if len(duration) else None, p75=float(duration.quantile(.75)) if len(duration) else None)
        item_columns = COLUMNS['order_items']
        promo_columns = COLUMNS['promotions']
        exceptions = {f'unknown_{slot}': bounded(items, mask, item_columns, examples) for slot, mask in unknown_masks.items()}
        exceptions.update({name: bounded(items, mask, item_columns, examples) for name, mask in {
            'same_code_both_slots': same, 'both_promotion_codes': a.notna() & b.notna(),
            'has_code_zero_discount': present & states.eq('zero'), 'no_code_positive_discount': ~present & states.eq('positive'),
            **{'discount_' + s: states.eq(s) for s in ['negative', 'NULL', 'non_numeric', 'non_finite']}}.items()})
        exceptions.update({name: bounded(promos, mask, promo_columns, examples) for name, mask in {
            'duplicate_promotion_key_rows': duplicate, 'null_promotion_key_rows': keys.isna(),
            'invalid_start_date': start_states.eq('invalid'), 'invalid_end_date': end_states.eq('invalid'),
            'null_start_date': start_states.eq('NULL'), 'null_end_date': end_states.eq('NULL'),
            'reversed_date_interval': reversed_dates}.items()})
        hashes = {'order_items': hashlib.sha256(), 'promotions': hashlib.sha256()}
        for i, (first, second, group, (value, state)) in enumerate(zip(a, b, groups, amounts)):
            hash_row(hashes['order_items'], [i + 2, first, second, group, state, decimal_text(value)])
        for i in range(p):
            sd, ed = start.iloc[i], end.iloc[i]
            hash_row(hashes['promotions'], [i + 2, keys.iloc[i], normalized(promos.promo_type).iloc[i],
                     normalized(promos.applicable_category).iloc[i], start_states.iloc[i], sd.date().isoformat() if pd.notna(sd) else None,
                     end_states.iloc[i], ed.date().isoformat() if pd.notna(ed) else None,
                     (ed.date() - sd.date()).days if both_valid.iloc[i] else None])
        reports = dict(column_profile=pd.DataFrame(profile, columns=PROFILE_COLUMNS), null_summary=pd.DataFrame(null_summary),
                       text_null_tokens=pd.DataFrame(null_tokens, columns=['table', 'column', 'token', 'rows']),
                       code_presence=pd.DataFrame([dict(group=g, rows=counts[g], percent_all=100 * counts[g] / n if n else None) for g in PRESENCE]),
                       reference_keys=pd.DataFrame(refs), discount_by_code_presence=pd.DataFrame(discount_cross),
                       promo_type=pd.DataFrame(type_counts, columns=FREQUENCY_COLUMNS),
                       applicable_category=pd.DataFrame(category_counts, columns=FREQUENCY_COLUMNS),
                       dates=pd.DataFrame(date_rows), duration_days=pd.DataFrame([duration_summary]))
        checks = dict(presence_groups_partition_all_items=sum(counts.values()) == n,
                      discount_groups_partition_all_items=sum(r['rows'] for r in discount_cross) == n,
                      references_partition_non_null_uses=all(r['known_reference_uses'] + r['unknown_reference_uses'] == r['non_null_uses'] for r in refs),
                      dates_partition_promotions=all(r['null_rows'] + r['invalid_non_null_rows'] + r['valid_rows'] == p for r in date_rows),
                      duration_groups_partition_promotions=len(duration) + int(reversed_dates.sum()) + p - int(both_valid.sum()) == p)
        return dict(metrics=metrics, reports=reports, checks=checks, exceptions=exceptions,
                    distribution_coverage={'promo_type': type_coverage, 'applicable_category': category_coverage},
                    ledger_fingerprints={name: h.hexdigest() for name, h in hashes.items()})
    return SimpleNamespace(
        argparse=argparse,
        csv=csv,
        hashlib=hashlib,
        re=re,
        sys=sys,
        Counter=Counter,
        date=date,
        datetime=datetime,
        timezone=timezone,
        Decimal=Decimal,
        InvalidOperation=InvalidOperation,
        Path=Path,
        pd=pd,
        digest=digest,
        equivalent=equivalent,
        NA_TOKENS=NA_TOKENS,
        read_table=read_table,
        ROOT=ROOT,
        COLUMNS=COLUMNS,
        SLOTS=SLOTS,
        PRESENCE=PRESENCE,
        DISCOUNTS=DISCOUNTS,
        PROFILE_COLUMNS=PROFILE_COLUMNS,
        FREQUENCY_COLUMNS=FREQUENCY_COLUMNS,
        read_sources=read_sources,
        null_kind=null_kind,
        normalized=normalized,
        discount_value=discount_value,
        strict_dates=strict_dates,
        hash_row=hash_row,
        decimal_text=decimal_text,
        bounded=bounded,
        frequency=frequency,
        analyze=analyze,
    )


@cache
def v07():
    """V07: bounce-rate distribution, daily coverage and conditional scale interpretation."""

    import argparse
    import csv
    import hashlib
    import math
    import re
    import statistics
    import sys
    from collections import Counter
    from datetime import date, datetime, timedelta, timezone
    from decimal import Decimal, InvalidOperation
    from pathlib import Path

    import pandas as pd

    digest = v02().digest
    equivalent = v04().equivalent
    number = v05().number
    bounded = v06().bounded
    decimal_text = v06().decimal_text
    hash_row = v06().hash_row
    normalized = v06().normalized
    null_kind = v06().null_kind
    read_sources = v06().read_sources
    strict_dates = v06().strict_dates
    NA_TOKENS = source_profiles().NA_TOKENS


    ROOT = PROJECT_ROOT
    REQUIRED = ['date', 'bounce_rate']
    FEATURES = ['sessions', 'unique_visitors', 'page_views', 'avg_session_duration_sec']
    QUANTILES = [('p01', .01), ('p05', .05), ('p25', .25), ('p75', .75), ('p95', .95), ('p99', .99)]
    BOUNDS = [(Decimal('.001'), 'positive_below_0.001'), (Decimal('.003'), '[0.001,0.003)'),
              (Decimal('.004'), '[0.003,0.004)'), (Decimal('.005'), '[0.004,0.005)'),
              (Decimal('.006'), '[0.005,0.006)'), (Decimal('.01'), '[0.006,0.01)'),
              (Decimal('.1'), '[0.01,0.1)'), (Decimal(1), '[0.1,1)')]
    BUCKETS = ['negative', 'zero', *[label for _, label in BOUNDS], 'one', 'above_one', 'NULL', 'non_numeric', 'non_finite']


    def read_source(path):
        return read_sources({'web_traffic': path})['web_traffic']


    def bucket(value, reason):
        if reason != 'finite':
            return 'NULL' if reason == 'missing' else reason
        if value < 0:
            return 'negative'
        if value == 0:
            return 'zero'
        if value == 1:
            return 'one'
        for upper, label in BOUNDS:
            if value < upper:
                return label
        return 'above_one'


    def summarize(values):
        series = pd.Series([float(v) for v in values], dtype=float)
        result = dict(count=len(series), minimum=float(series.min()) if len(series) else None,
                      maximum=float(series.max()) if len(series) else None, mean=float(series.mean()) if len(series) else None,
                      median=float(series.median()) if len(series) else None,
                      std_sample=float(series.std(ddof=1)) if len(series) > 1 else None,
                      std_population=float(series.std(ddof=0)) if len(series) else None)
        result.update({name: float(series.quantile(q)) if len(series) else None for name, q in QUANTILES})
        return result


    def missing_examples(missing, limit):
        return dict(cases=len(missing) if missing is not None else None,
                    examples_reported=min(len(missing), limit) if missing is not None else 0,
                    examples_omitted=max(0, len(missing) - limit) if missing is not None else None,
                    records=[dict(date=d) for d in (missing or [])[:limit]])


    def analyze(web_traffic, examples=20):
        if not 1 <= examples <= 20:
            raise ValueError('examples must be between 1 and 20')
        missing_columns = [c for c in REQUIRED if c not in web_traffic]
        if missing_columns:
            raise ValueError(f'web_traffic: missing required columns {missing_columns}')
        frame = web_traffic.copy(deep=True).reset_index(drop=True)
        n = len(frame)
        parsed = frame.bounce_rate.map(number).tolist()
        values = [value for value, reason in parsed if reason == 'finite']
        reasons = pd.Series([reason for _, reason in parsed], dtype=object)
        bins = [bucket(value, reason) for value, reason in parsed]
        counts = Counter(bins)
        stats = summarize(values)
        raw_distinct = int(normalized(frame.bounce_rate).nunique(dropna=True))
        metrics = dict(rows=n, bounce_null_rows=counts['NULL'], bounce_non_numeric_rows=counts['non_numeric'],
                       bounce_non_finite_rows=counts['non_finite'], bounce_finite_rows=len(values),
                       bounce_negative_rows=counts['negative'], bounce_zero_rows=counts['zero'], bounce_above_one_rows=counts['above_one'],
                       bounce_in_unit_interval_rows=sum(0 <= value <= 1 for value in values),
                       bounce_distinct_finite=len(set(values)), bounce_distinct_non_null_lexical=raw_distinct,
                       bounce_min=stats['minimum'], bounce_max=stats['maximum'], bounce_mean=stats['mean'],
                       bounce_median=stats['median'], bounce_std_sample=stats['std_sample'], bounce_std_population=stats['std_population'])
        metrics.update({'bounce_' + name: stats[name] for name, _ in QUANTILES})
        metrics['all_rows_finite_in_unit_interval'] = bool(n and metrics['bounce_in_unit_interval_rows'] == n)
        value_counts = Counter(values)
        top = sorted(value_counts.items(), key=lambda pair: (-pair[1], pair[0]))[:20]
        frequency = [dict(value=float(value), rows=count, percent_all=100 * count / n) for value, count in top]
        coverage = dict(distinct_finite=len(value_counts), finite_values_reported=len(top),
                        finite_rows_omitted=len(values) - sum(count for _, count in top), limit=20)
        dates, date_states = strict_dates(frame.date)
        valid_dates = dates[date_states.eq('valid')]
        date_counts = valid_dates.value_counts().sort_index()
        unique_dates = pd.DatetimeIndex(date_counts.index)
        calendar = pd.date_range(unique_dates.min(), unique_dates.max(), freq='D') if len(unique_dates) else None
        missing = [d.date().isoformat() for d in calendar.difference(unique_dates)] if calendar is not None else None
        duplicates = date_states.eq('valid') & dates.duplicated(keep=False)
        one_per_observed = bool(n and len(valid_dates) == n and len(unique_dates) == n)
        metrics.update(date_null_rows=int(date_states.eq('NULL').sum()), date_invalid_non_null_rows=int(date_states.eq('invalid').sum()),
                       date_valid_rows=len(valid_dates), date_distinct_valid=len(unique_dates),
                       duplicate_dates=int(date_counts.gt(1).sum()), duplicate_date_rows=int(duplicates.sum()),
                       duplicate_date_excess=int((date_counts - 1).sum()),
                       date_min=unique_dates.min().date().isoformat() if len(unique_dates) else None,
                       date_max=unique_dates.max().date().isoformat() if len(unique_dates) else None,
                       expected_calendar_days=len(calendar) if calendar is not None else None,
                       missing_calendar_days=len(missing) if missing is not None else None,
                       one_record_per_observed_day=one_per_observed,
                       complete_one_record_per_calendar_day=bool(one_per_observed and missing == []),
                       valid_dates_in_source_order=bool(valid_dates.is_monotonic_increasing) if len(valid_dates) else None)
        profile = []
        for column in frame:
            kinds = frame[column].map(null_kind)
            nulls = int(kinds.ne('non_null').sum())
            profile.append(dict(column=column, parsed_dtype=frame.attrs.get('parsed_dtypes', {}).get(column, str(frame[column].dtype)),
                                rows=n, null_rows=nulls, null_percent=100 * nulls / n if n else None,
                                missing_or_empty_rows=int(kinds.eq('missing_or_empty').sum()), text_null_token_rows=int(kinds.eq('text_null_token').sum()),
                                distinct_non_null=int(normalized(frame[column]).nunique(dropna=True))))
        correlations = []
        features = [name for name in FEATURES if name in frame]
        feature_pairs = {c: frame[c].map(number).tolist() for c in features}
        x = pd.Series([float(v) if reason == 'finite' else None for v, reason in parsed], dtype=float)
        for feature in features:
            y = pd.Series([float(v) if reason == 'finite' else None for v, reason in feature_pairs[feature]], dtype=float)
            mask = x.notna() & y.notna()
            reason = ('insufficient_pairs' if int(mask.sum()) < 2 else 'constant_bounce_rate' if x[mask].nunique() < 2
                      else 'constant_predictor' if y[mask].nunique() < 2 else 'defined')
            correlations.append(dict(feature=feature, paired_rows=int(mask.sum()), excluded_rows=int((~mask).sum()), reason=reason,
                                      pearson=float(x[mask].corr(y[mask])) if reason == 'defined' else None))
        page_ratio = []
        if 'sessions' in features and 'page_views' in features:
            ratios = [pages / sessions for (sessions, sr), (pages, pr) in zip(feature_pairs['sessions'], feature_pairs['page_views'])
                      if sr == pr == 'finite' and sessions > 0 and pages >= 0]
            page_ratio = [dict(metric='page_views_per_session', **summarize(ratios), excluded_rows=n - len(ratios))]
        illustrative = dict(stats)
        illustrative.update({name: value * 100 if value is not None else None for name, value in stats.items() if name != 'count'})
        selected_columns = [*REQUIRED, *features]
        examples_by_group = {name: bounded(frame, mask, selected_columns, examples) for name, mask in {
            'bounce_NULL': reasons.eq('missing'), 'bounce_non_numeric': reasons.eq('non_numeric'),
            'bounce_non_finite': reasons.eq('non_finite'), 'bounce_negative': pd.Series([b == 'negative' for b in bins], dtype=bool),
            'bounce_above_one': pd.Series([b == 'above_one' for b in bins], dtype=bool),
            'date_NULL': date_states.eq('NULL'), 'date_invalid': date_states.eq('invalid'), 'duplicate_date_rows': duplicates}.items()}
        examples_by_group['missing_calendar_dates'] = missing_examples(missing, examples)
        evidence = hashlib.sha256()
        for i, (value, reason) in enumerate(parsed):
            parsed_date = dates.iloc[i]
            hash_row(evidence, [i + 2, decimal_text(value), reason, bins[i], date_states.iloc[i],
                               parsed_date.date().isoformat() if pd.notna(parsed_date) else None,
                               *[[c, decimal_text(feature_pairs[c][i][0]), feature_pairs[c][i][1]] for c in features]])
        reports = dict(column_profile=pd.DataFrame(profile), bounce_statistics=pd.DataFrame([stats]),
                       bounce_distribution=pd.DataFrame([dict(bucket=b, rows=counts[b], percent_all=100 * counts[b] / n if n else None) for b in BUCKETS]),
                       bounce_value_top20=pd.DataFrame(frequency, columns=['value', 'rows', 'percent_all']),
                       conditional_percent_illustration=pd.DataFrame([illustrative]),
                       descriptive_correlations=pd.DataFrame(correlations, columns=['feature', 'paired_rows', 'excluded_rows', 'reason', 'pearson']),
                       page_views_per_session=pd.DataFrame(page_ratio, columns=['metric', *stats.keys(), 'excluded_rows']))
        checks = dict(value_states_partition_all_rows=len(values) + sum(counts[b] for b in ['NULL', 'non_numeric', 'non_finite']) == n,
                      histogram_partitions_all_rows=sum(counts.values()) == n,
                      dates_partition_all_rows=metrics['date_valid_rows'] + metrics['date_null_rows'] + metrics['date_invalid_non_null_rows'] == n,
                      duplicate_accounting=metrics['date_valid_rows'] == metrics['date_distinct_valid'] + metrics['duplicate_date_excess'],
                      calendar_accounting=calendar is None or len(calendar) == len(unique_dates) + len(missing))
        return dict(metrics=metrics, reports=reports, checks=checks, exceptions=examples_by_group,
                    frequency_coverage=coverage, ledger_fingerprint=evidence.hexdigest())
    return SimpleNamespace(
        argparse=argparse,
        csv=csv,
        hashlib=hashlib,
        math=math,
        re=re,
        statistics=statistics,
        sys=sys,
        Counter=Counter,
        date=date,
        datetime=datetime,
        timedelta=timedelta,
        timezone=timezone,
        Decimal=Decimal,
        InvalidOperation=InvalidOperation,
        Path=Path,
        pd=pd,
        digest=digest,
        equivalent=equivalent,
        number=number,
        bounded=bounded,
        decimal_text=decimal_text,
        hash_row=hash_row,
        normalized=normalized,
        null_kind=null_kind,
        read_sources=read_sources,
        strict_dates=strict_dates,
        NA_TOKENS=NA_TOKENS,
        ROOT=ROOT,
        REQUIRED=REQUIRED,
        FEATURES=FEATURES,
        QUANTILES=QUANTILES,
        BOUNDS=BOUNDS,
        BUCKETS=BUCKETS,
        read_source=read_source,
        bucket=bucket,
        summarize=summarize,
        missing_examples=missing_examples,
        analyze=analyze,
    )


@cache
def v08():
    """V08: daily traffic-source labels, temporal structure and vocabulary comparison."""

    import argparse
    import csv
    import hashlib
    import re
    import sys
    from collections import Counter, defaultdict
    from datetime import date, datetime, timedelta, timezone
    from pathlib import Path

    import pandas as pd

    digest = v02().digest
    equivalent = v04().equivalent
    bounded = v06().bounded
    hash_row = v06().hash_row
    normalized = v06().normalized
    null_kind = v06().null_kind
    read_sources = v06().read_sources
    strict_dates = v06().strict_dates
    missing_examples = v07().missing_examples
    NA_TOKENS = source_profiles().NA_TOKENS


    ROOT = PROJECT_ROOT
    COLUMNS = {'web_traffic': ['date', 'traffic_source'], 'customers': ['acquisition_channel']}
    REFERENCE_LABELS = {"organic_search", "paid_search", "social_media", "email_campaign", "referral", "direct"}
    STATES = ['NULL', 'blank_whitespace', 'malformed', 'unexpected_reference_label', 'reference_label']
    USABLE = {'unexpected_reference_label', 'reference_label'}
    SCHEMAS = {
        'column_profile': ['table', 'column', 'parsed_dtype', 'rows', 'null_rows', 'empty_or_missing_rows', 'text_null_token_rows', 'distinct_non_null'],
        'label_quality': ['table', 'column', 'state', 'rows', 'percent_all'],
        'web_label_rows': ['label', 'rows', 'percent_rows'],
        'customer_label_rows': ['label', 'rows', 'percent_rows'],
        'daily_distribution': ['label', 'days', 'percent_eligible_days'],
        'yearly_distribution': ['year', 'label', 'days', 'percent_eligible_year_days', 'present'],
        'yearly_coverage': ['year', 'valid_date_rows', 'distinct_dates', 'eligible_days', 'excluded_days', 'labels_present', 'all_reference_labels_present'],
        'transitions': ['from_label', 'to_label', 'pairs', 'changed'],
        'run_length_distribution': ['length_days', 'runs', 'covered_days'],
        'run_statistics': ['group', 'runs', 'covered_days', 'minimum', 'maximum', 'mean', 'median', 'p95'],
    }


    def label_state(raw):
        if null_kind(raw) != 'non_null':
            return 'NULL'
        text = str(raw)
        if not text.strip():
            return 'blank_whitespace'
        if not re.fullmatch(r'[a-z][a-z0-9_]*', text):
            return 'malformed'
        return 'reference_label' if text in REFERENCE_LABELS else 'unexpected_reference_label'


    def record_distribution(labels):
        counts = Counter(labels)
        return [dict(label=label, rows=count, percent_rows=100 * count / len(labels))
                for label, count in sorted(counts.items(), key=lambda pair: (pair[0] is None, str(pair[0])))]


    def run_statistics(runs, labels):
        result = []
        for label in [None, *labels]:
            lengths = pd.Series([r['length_days'] for r in runs if label is None or r['label'] == label], dtype='int64')
            result.append(dict(group='all_labels' if label is None else label, runs=len(lengths), covered_days=int(lengths.sum()),
                               minimum=int(lengths.min()) if len(lengths) else None, maximum=int(lengths.max()) if len(lengths) else None,
                               mean=float(lengths.mean()) if len(lengths) else None, median=float(lengths.median()) if len(lengths) else None,
                               p95=float(lengths.quantile(.95)) if len(lengths) else None))
        return result


    def analyze(web_traffic, customers, examples=20):
        if not 1 <= examples <= 20:
            raise ValueError('examples must be between 1 and 20')
        frames = {'web_traffic': web_traffic.copy(deep=True).reset_index(drop=True),
                  'customers': customers.copy(deep=True).reset_index(drop=True)}
        for name, required in COLUMNS.items():
            absent = [c for c in required if c not in frames[name]]
            if absent:
                raise ValueError(f'{name}: missing required columns {absent}')
        web, customer = frames['web_traffic'], frames['customers']
        n, nc = len(web), len(customer)
        labels, acquired = normalized(web.traffic_source), normalized(customer.acquisition_channel)
        states, customer_states = web.traffic_source.map(label_state), customer.acquisition_channel.map(label_state)
        dates, date_states = strict_dates(web.date)
        valid = date_states.eq('valid')
        date_counts = dates[valid].value_counts().sort_index()
        calendar = pd.date_range(date_counts.index.min(), date_counts.index.max(), freq='D') if len(date_counts) else None
        missing = [v.date().isoformat() for v in calendar.difference(date_counts.index)] if calendar is not None else None
        duplicate_mask = valid & dates.duplicated(keep=False)
        eligible = valid & ~duplicate_mask & states.isin(USABLE)
        per_day = pd.DataFrame({'date': dates[valid], 'label': labels[valid], 'null': states[valid].eq('NULL'),
                                'invalid': states[valid].isin(['blank_whitespace', 'malformed'])}).groupby('date').agg(
                                    rows=('label', 'size'), distinct_labels=('label', 'nunique'),
                                    nulls=('null', 'sum'), invalid=('invalid', 'sum'))
        timeline = pd.DataFrame({'date': dates[eligible], 'label': labels[eligible]}).sort_values('date').reset_index(drop=True)
        ordinals = timeline.date.map(lambda value: value.date().toordinal()).astype('int64')
        adjacent = ordinals.diff().eq(1)
        previous = timeline.label.shift()
        changed = adjacent & timeline.label.ne(previous)
        run_ids = (~adjacent | timeline.label.ne(previous)).cumsum()
        grouped = timeline.groupby(run_ids).agg(label=('label', 'first'), start=('date', 'min'), end=('date', 'max'), length=('date', 'size'))
        runs = [dict(label=row.label, start_date=row.start.date().isoformat(), end_date=row.end.date().isoformat(), length_days=int(row.length))
                for row in grouped.itertuples(index=False)]
        pairs = pd.DataFrame({'from_label': previous[adjacent], 'to_label': timeline.label[adjacent]})
        transitions = [dict(from_label=a, to_label=b, pairs=int(count), changed=a != b)
                       for (a, b), count in pairs.groupby(['from_label', 'to_label']).size().sort_index().items()]
        longest = max((r['length_days'] for r in runs), default=None)
        max_runs = [r for r in runs if r['length_days'] == longest]
        web_set, customer_set = set(labels.dropna()), set(acquired.dropna())
        analysis_labels = sorted(REFERENCE_LABELS | set(labels[states.isin(USABLE)]))
        day_counts = Counter(timeline.label)
        year_counts = Counter((d.year, label) for d, label in zip(timeline.date, timeline.label))
        eligible_by_year = Counter(d.year for d in timeline.date)
        years = sorted({int(d.year) for d in dates[valid]})
        profile, quality = [], []
        for name, frame in frames.items():
            for column in frame:
                kinds = frame[column].map(null_kind)
                profile.append(dict(table=name, column=column, parsed_dtype=frame.attrs.get('parsed_dtypes', {}).get(column, str(frame[column].dtype)),
                                    rows=len(frame), null_rows=int(kinds.ne('non_null').sum()), empty_or_missing_rows=int(kinds.eq('missing_or_empty').sum()),
                                    text_null_token_rows=int(kinds.eq('text_null_token').sum()), distinct_non_null=int(normalized(frame[column]).nunique(dropna=True))))
        for table, column, state_series in [('web_traffic', 'traffic_source', states), ('customers', 'acquisition_channel', customer_states)]:
            quality.extend(dict(table=table, column=column, state=s, rows=int(state_series.eq(s).sum()),
                                percent_all=100 * int(state_series.eq(s).sum()) / len(state_series) if len(state_series) else None) for s in STATES)
        one_row_per_observed = bool(n and int(valid.sum()) == n and len(date_counts) == n)
        one_label_per_day = bool(len(per_day) and per_day.distinct_labels.eq(1).all() and per_day.nulls.eq(0).all() and per_day.invalid.eq(0).all())
        ids = normalized(customer.customer_id) if 'customer_id' in customer else None
        metrics = dict(web_rows=n, customers_rows=nc, date_null_rows=int(date_states.eq('NULL').sum()), date_invalid_rows=int(date_states.eq('invalid').sum()),
                       valid_date_rows=int(valid.sum()), distinct_dates=len(date_counts), duplicate_dates=int(date_counts.gt(1).sum()),
                       duplicate_date_rows=int(duplicate_mask.sum()), duplicate_date_excess=int((date_counts - 1).sum()),
                       date_min=date_counts.index.min().date().isoformat() if len(date_counts) else None,
                       date_max=date_counts.index.max().date().isoformat() if len(date_counts) else None,
                       expected_calendar_days=len(calendar) if calendar is not None else None, missing_calendar_days=len(missing) if missing is not None else None,
                       traffic_source_null_rows=int(states.eq('NULL').sum()), traffic_source_distinct_non_null=len(web_set),
                       traffic_source_empty_or_missing_rows=sum(null_kind(v) == 'missing_or_empty' for v in web.traffic_source),
                       traffic_source_whitespace_only_rows=int(states.eq('blank_whitespace').sum()), traffic_source_malformed_rows=int(states.eq('malformed').sum()),
                       traffic_source_unexpected_reference_rows=int(states.eq('unexpected_reference_label').sum()),
                       customers_channel_null_rows=int(customer_states.eq('NULL').sum()), customers_channel_distinct_non_null=len(customer_set),
                       days_without_non_null_label=int(per_day.distinct_labels.eq(0).sum()), days_with_one_non_null_label=int(per_day.distinct_labels.eq(1).sum()),
                       days_with_multiple_non_null_labels=int(per_day.distinct_labels.gt(1).sum()),
                       days_with_any_null_label=int(per_day.nulls.gt(0).sum()), days_with_any_malformed_label=int(per_day.invalid.gt(0).sum()),
                       one_record_per_observed_day=one_row_per_observed, one_usable_label_per_observed_day=one_label_per_day,
                       complete_one_record_and_label_per_calendar_day=bool(one_row_per_observed and one_label_per_day and missing == []),
                       eligible_days=len(timeline), excluded_valid_days=len(date_counts) - len(timeline), excluded_web_rows=n - len(timeline),
                       consecutive_calendar_pairs=int(adjacent.sum()), label_changes=int(changed.sum()), unchanged_pairs=int((adjacent & ~changed).sum()),
                       calendar_segments=int((~adjacent).sum()), run_count=len(runs), longest_run_days=longest,
                       label_sets_equal=web_set == customer_set, both_label_sets_nonempty=bool(web_set and customer_set),
                       common_labels=len(web_set & customer_set), web_only_labels=len(web_set - customer_set), customer_only_labels=len(customer_set - web_set),
                       customer_id_column_present=ids is not None, distinct_customer_ids=int(ids.nunique()) if ids is not None else None,
                       null_customer_id_rows=int(ids.isna().sum()) if ids is not None else None,
                       duplicate_customer_id_excess=int(ids.dropna().duplicated().sum()) if ids is not None else None,
                       one_record_per_observed_customer=bool(nc and ids.notna().all() and not ids.duplicated().any()) if ids is not None else None,
                       **{'days_' + label: day_counts[label] for label in sorted(REFERENCE_LABELS)})
        yearly = [dict(year=year, label=label, days=year_counts[year, label],
                       percent_eligible_year_days=100 * year_counts[year, label] / eligible_by_year[year] if eligible_by_year[year] else None,
                       present=year_counts[year, label] > 0) for year in years for label in analysis_labels]
        yearly_coverage = [dict(year=year, valid_date_rows=int(dates[valid].dt.year.eq(year).sum()),
                                distinct_dates=sum(d.year == year for d in date_counts.index), eligible_days=eligible_by_year[year],
                                excluded_days=sum(d.year == year for d in date_counts.index) - eligible_by_year[year],
                                labels_present=sum(year_counts[year, label] > 0 for label in analysis_labels),
                                all_reference_labels_present=all(year_counts[year, label] > 0 for label in REFERENCE_LABELS)) for year in years]
        run_counts = Counter(r['length_days'] for r in runs)
        records = dict(column_profile=profile, label_quality=quality, web_label_rows=record_distribution(labels), customer_label_rows=record_distribution(acquired),
                       daily_distribution=[dict(label=label, days=day_counts[label], percent_eligible_days=100 * day_counts[label] / len(timeline) if len(timeline) else None) for label in analysis_labels],
                       yearly_distribution=yearly, yearly_coverage=yearly_coverage, transitions=transitions,
                       run_length_distribution=[dict(length_days=length, runs=count, covered_days=length * count) for length, count in sorted(run_counts.items())],
                       run_statistics=run_statistics(runs, analysis_labels))
        exceptions = {name: bounded(web, mask, COLUMNS['web_traffic'], examples) for name, mask in {
            'traffic_source_NULL': states.eq('NULL'), 'traffic_source_whitespace': states.eq('blank_whitespace'),
            'traffic_source_malformed': states.eq('malformed'), 'traffic_source_unexpected_reference_label': states.eq('unexpected_reference_label'),
            'date_NULL': date_states.eq('NULL'), 'date_invalid': date_states.eq('invalid'), 'duplicate_date_rows': duplicate_mask}.items()}
        exceptions.update({name: bounded(customer, mask, ['customer_id', 'acquisition_channel'] if ids is not None else ['acquisition_channel'], examples)
                           for name, mask in {'customer_channel_NULL': customer_states.eq('NULL'),
                               'customer_channel_malformed': customer_states.isin(['blank_whitespace', 'malformed']),
                               'customer_channel_unexpected_reference_label': customer_states.eq('unexpected_reference_label')}.items()})
        exceptions['missing_calendar_dates'] = missing_examples(missing, examples)
        exceptions['longest_runs'] = dict(cases=len(max_runs), examples_reported=min(examples, len(max_runs)),
                                        examples_omitted=max(0, len(max_runs) - examples), records=max_runs[:examples])
        hashes = {name: hashlib.sha256() for name in ['web_traffic', 'customers', 'runs']}
        for i in range(n):
            hash_row(hashes['web_traffic'], [i + 2, date_states.iloc[i], dates.iloc[i].date().isoformat() if valid.iloc[i] else None,
                                           labels.iloc[i], states.iloc[i], bool(eligible.iloc[i])])
        for i in range(nc):
            hash_row(hashes['customers'], [i + 2, ids.iloc[i] if ids is not None else None, acquired.iloc[i], customer_states.iloc[i]])
        for run in runs:
            hash_row(hashes['runs'], [run[c] for c in ['label', 'start_date', 'end_date', 'length_days']])
        comparison = dict(web_labels=sorted(web_set), customer_labels=sorted(customer_set), common=sorted(web_set & customer_set),
                          web_only=sorted(web_set - customer_set), customers_only=sorted(customer_set - web_set),
                          interpretation='Exact non-NULL label names only; no customer/day/session JOIN or semantic equivalence is established.')
        checks = dict(raw_web_distribution_partitions_rows=sum(r['rows'] for r in records['web_label_rows']) == n,
                      raw_customer_distribution_partitions_rows=sum(r['rows'] for r in records['customer_label_rows']) == nc,
                      daily_distribution_partitions_eligible_days=sum(day_counts.values()) == len(timeline),
                      yearly_distribution_partitions_eligible_days=sum(r['days'] for r in yearly) == len(timeline),
                      calendar_accounting=calendar is None or len(calendar) == len(date_counts) + len(missing),
                      valid_days_partition_by_label_count=metrics['days_without_non_null_label'] + metrics['days_with_one_non_null_label'] + metrics['days_with_multiple_non_null_labels'] == len(date_counts),
                      transition_accounting=sum(r['pairs'] for r in transitions) == metrics['consecutive_calendar_pairs'] == metrics['label_changes'] + metrics['unchanged_pairs'],
                      run_count_matches_changes_and_segments=len(runs) == metrics['label_changes'] + metrics['calendar_segments'],
                      run_lengths_cover_eligible_days=sum(r['length_days'] for r in runs) == len(timeline),
                      dates_partition_rows=metrics['valid_date_rows'] + metrics['date_null_rows'] + metrics['date_invalid_rows'] == n)
        return dict(metrics=metrics, reports={name: pd.DataFrame(rows, columns=SCHEMAS[name]) for name, rows in records.items()}, exceptions=exceptions,
                    label_set_comparison=comparison, ledger_fingerprints={name: h.hexdigest() for name, h in hashes.items()}, checks=checks)
    return SimpleNamespace(
        argparse=argparse,
        csv=csv,
        hashlib=hashlib,
        re=re,
        sys=sys,
        Counter=Counter,
        defaultdict=defaultdict,
        date=date,
        datetime=datetime,
        timedelta=timedelta,
        timezone=timezone,
        Path=Path,
        pd=pd,
        digest=digest,
        equivalent=equivalent,
        bounded=bounded,
        hash_row=hash_row,
        normalized=normalized,
        null_kind=null_kind,
        read_sources=read_sources,
        strict_dates=strict_dates,
        missing_examples=missing_examples,
        NA_TOKENS=NA_TOKENS,
        ROOT=ROOT,
        COLUMNS=COLUMNS,
        REFERENCE_LABELS=REFERENCE_LABELS,
        STATES=STATES,
        USABLE=USABLE,
        SCHEMAS=SCHEMAS,
        label_state=label_state,
        record_distribution=record_distribution,
        run_statistics=run_statistics,
        analyze=analyze,
    )


@cache
def v09():
    """V09: submission-template contract, future calendar and historical-sales separation."""

    import argparse
    import calendar
    import csv
    import hashlib
    import io
    import re
    import sys
    from collections import Counter
    from datetime import date, datetime, timedelta, timezone
    from decimal import Decimal, InvalidOperation
    from pathlib import Path

    import pandas as pd

    digest = v02().digest
    equivalent = v04().equivalent
    number = v05().number
    bounded = v06().bounded
    decimal_text = v06().decimal_text
    hash_row = v06().hash_row
    normalized = v06().normalized
    null_kind = v06().null_kind
    read_sources = v06().read_sources
    strict_dates = v06().strict_dates
    missing_examples = v07().missing_examples
    NA_TOKENS = source_profiles().NA_TOKENS
    is_identifier = table_reader().is_identifier


    ROOT = PROJECT_ROOT
    EXPECTED = ['Date', 'Revenue', 'COGS']
    TARGETS = ['Revenue', 'COGS']
    TABLES = ['sample_submission', 'sales']
    SCHEMAS = {
        'column_profile': ['table', 'column', 'position', 'parsed_dtype', 'rows', 'null_rows', 'empty_or_missing_rows', 'text_null_token_rows', 'distinct_non_null'],
        'dates': ['table', 'rows', 'null_rows', 'invalid_rows', 'valid_rows', 'distinct_dates', 'duplicate_dates', 'duplicate_date_rows', 'duplicate_excess',
                  'date_min', 'date_max', 'expected_calendar_days', 'missing_calendar_days', 'one_record_per_observed_day', 'complete_daily_calendar',
                  'valid_dates_sorted_in_source', 'backward_source_steps', 'original_rows_daily_ascending', 'unique_date_frequency',
                  'contains_2024_02_29', 'expected_leap_days', 'observed_leap_days', 'missing_leap_days'],
        'target_values': ['table', 'target', 'rows', 'null_rows', 'non_numeric_rows', 'non_finite_rows', 'finite_rows', 'negative_rows', 'zero_rows', 'positive_rows',
                          'distinct_finite', 'minimum', 'maximum', 'constant_value', 'observed_pattern', 'all_finite_nonnegative', 'role'],
        'date_steps': ['table', 'calendar_days_between_distinct_dates', 'pairs'],
        'leap_days': ['table', 'year', 'date', 'present'],
    }


    def table_fingerprint(columns, rows):
        hasher = hashlib.sha256()
        hash_row(hasher, columns)
        for row in rows:
            hash_row(hasher, row)
        return hasher.hexdigest()


    def inspect_roundtrip(frame):
        """Only the supplied template is serialized in memory; no forecast is created."""
        lexical = frame.astype(object).where(frame.notna(), '').astype(str)
        columns = list(frame.columns)
        before = lexical.values.tolist()
        content = lexical.to_csv(index=False, lineterminator='\n')
        decoded = list(csv.reader(io.StringIO(content), strict=True))
        after_columns, after = decoded[0], decoded[1:]
        identifiers = {c: 'string' for c in columns if is_identifier(c)}
        observed_after = pd.read_csv(io.StringIO(content), dtype=identifiers, low_memory=False, skip_blank_lines=False).dtypes.astype(str).to_dict()
        position = columns.index('Date')
        result = dict(column_order_preserved=columns == after_columns, row_count_preserved=len(before) == len(after),
                      ordered_date_lexemes_preserved=[r[position] for r in before] == [r[position] for r in after],
                      all_decoded_values_preserved=before == after,
                      before_fingerprint=table_fingerprint(columns, before), after_fingerprint=table_fingerprint(after_columns, after))
        return result, observed_after


    def target_pattern(values, rows):
        if not rows:
            return 'no_rows'
        if len(values) != rows:
            return 'contains_missing_or_invalid_values'
        if len(set(values)) == 1:
            return 'constant_zero' if values[0] == 0 else 'constant_nonzero'
        return 'varying_finite_values'


    def analyze(sample_submission, sales, examples=20):
        if not 1 <= examples <= 20:
            raise ValueError('examples must be between 1 and 20')
        frames = {'sample_submission': sample_submission.copy(deep=True).reset_index(drop=True),
                  'sales': sales.copy(deep=True).reset_index(drop=True)}
        for name, frame in frames.items():
            absent = [c for c in EXPECTED if c not in frame]
            if absent:
                raise ValueError(f'{name}: missing required columns {absent}')
        metrics, profiles, date_reports, target_reports, steps, leap_records, exceptions = {}, [], [], [], [], [], {}
        schemas, date_sets, fingerprints = {}, {}, {}
        for name, frame in frames.items():
            prefix = 'sample' if name == 'sample_submission' else 'sales'
            n = len(frame)
            inferred = frame.attrs.get('parsed_dtypes', {c: str(t) for c, t in frame.dtypes.items()})
            schemas[name] = dict(column_count=len(frame.columns), columns_in_order=list(frame.columns), expected_columns_in_order=EXPECTED,
                                 extra_columns=[c for c in frame if c not in EXPECTED], ordered_schema_matches_expected=list(frame.columns) == EXPECTED,
                                 observed_parsed_dtypes=inferred, row_identifier='Date (candidate only if non-NULL, valid and unique)')
            metrics[prefix + '_rows'] = n
            metrics[prefix + '_columns'] = len(frame.columns)
            null_cells = 0
            for position, column in enumerate(frame):
                kinds = frame[column].map(null_kind)
                nulls = int(kinds.ne('non_null').sum())
                null_cells += nulls
                profiles.append(dict(table=name, column=column, position=position, parsed_dtype=inferred[column], rows=n, null_rows=nulls,
                                     empty_or_missing_rows=int(kinds.eq('missing_or_empty').sum()), text_null_token_rows=int(kinds.eq('text_null_token').sum()),
                                     distinct_non_null=int(normalized(frame[column]).nunique(dropna=True))))
            metrics[prefix + '_null_cells'] = null_cells
            duplicate_full = frame.duplicated(keep=False)
            metrics[prefix + '_duplicate_full_rows_excess'] = int(frame.duplicated().sum())
            metrics[prefix + '_duplicate_full_rows_members'] = int(duplicate_full.sum())
            dates, states = strict_dates(frame.Date)
            valid = states.eq('valid')
            valid_dates = dates[valid]
            counts = valid_dates.value_counts().sort_index()
            unique = pd.DatetimeIndex(counts.index)
            date_sets[name] = {value.date() for value in unique}
            calendar_days = pd.date_range(unique.min(), unique.max(), freq='D') if len(unique) else None
            missing = [d.date().isoformat() for d in calendar_days.difference(unique)] if calendar_days is not None else None
            ordinal = valid_dates.map(lambda d: d.date().toordinal()).astype('int64')
            duplicate_dates = valid & dates.duplicated(keep=False)
            backward = pd.Series(False, index=frame.index)
            backward.loc[ordinal.index] = ordinal.diff().lt(0)
            expected_leaps = [date(year, 2, 29) for year in range(unique.min().year, unique.max().year + 1)
                              if calendar.isleap(year) and unique.min().date() <= date(year, 2, 29) <= unique.max().date()] if len(unique) else []
            leap_records.extend(dict(table=name, year=d.year, date=d.isoformat(), present=d in date_sets[name]) for d in expected_leaps)
            sorted_steps = Counter(b.toordinal() - a.toordinal() for a, b in zip(unique, unique[1:]))
            steps.extend(dict(table=name, calendar_days_between_distinct_dates=gap, pairs=count) for gap, count in sorted(sorted_steps.items()))
            one_per_day = bool(n and len(valid_dates) == n and len(unique) == n)
            summary = dict(table=name, rows=n, null_rows=int(states.eq('NULL').sum()), invalid_rows=int(states.eq('invalid').sum()),
                            valid_rows=len(valid_dates), distinct_dates=len(unique), duplicate_dates=int(counts.gt(1).sum()), duplicate_date_rows=int(duplicate_dates.sum()),
                            duplicate_excess=int((counts - 1).sum()), date_min=unique.min().date().isoformat() if len(unique) else None,
                            date_max=unique.max().date().isoformat() if len(unique) else None, expected_calendar_days=len(calendar_days) if calendar_days is not None else None,
                            missing_calendar_days=len(missing) if missing is not None else None, one_record_per_observed_day=one_per_day,
                            complete_daily_calendar=bool(one_per_day and missing == []), valid_dates_sorted_in_source=bool(valid_dates.is_monotonic_increasing) if len(valid_dates) else None,
                            backward_source_steps=int(backward.sum()), original_rows_daily_ascending=bool(one_per_day and ordinal.diff().iloc[1:].eq(1).all()),
                            unique_date_frequency='insufficient_distinct_dates' if len(unique) < 2 else 'daily' if missing == [] else 'gapped',
                            contains_2024_02_29=date(2024, 2, 29) in date_sets[name], expected_leap_days=len(expected_leaps),
                            observed_leap_days=sum(d.month == 2 and d.day == 29 for d in date_sets[name]), missing_leap_days=sum(d not in date_sets[name] for d in expected_leaps))
            date_reports.append(summary)
            metrics.update({prefix + '_' + key: value for key, value in summary.items() if key not in {'table', 'rows'}})
            schemas[name].update(first_row_date_lexeme=None if not n or pd.isna(frame.Date.iloc[0]) else str(frame.Date.iloc[0]),
                                 last_row_date_lexeme=None if not n or pd.isna(frame.Date.iloc[-1]) else str(frame.Date.iloc[-1]),
                                 valid_date_candidate_key=one_per_day)
            exceptions.update({name + '_' + group: bounded(frame, mask, EXPECTED, examples) for group, mask in {
                'date_NULL': states.eq('NULL'), 'date_invalid': states.eq('invalid'), 'duplicate_date_rows': duplicate_dates,
                'duplicate_full_rows': duplicate_full, 'backward_source_rows': backward}.items()})
            exceptions[name + '_missing_dates'] = missing_examples(missing, examples)
            parsed_targets = {}
            for target in TARGETS:
                parsed = frame[target].map(number).tolist()
                parsed_targets[target] = parsed
                values = [v for v, reason in parsed if reason == 'finite']
                target_reports.append(dict(table=name, target=target, rows=n, null_rows=sum(reason == 'missing' for _, reason in parsed),
                    non_numeric_rows=sum(reason == 'non_numeric' for _, reason in parsed), non_finite_rows=sum(reason == 'non_finite' for _, reason in parsed),
                    finite_rows=len(values), negative_rows=sum(v < 0 for v in values), zero_rows=sum(v == 0 for v in values), positive_rows=sum(v > 0 for v in values),
                    distinct_finite=len(set(values)), minimum=min(values, default=None), maximum=max(values, default=None),
                    constant_value=values[0] if len(values) == n and n and len(set(values)) == 1 else None,
                    observed_pattern=target_pattern(values, n), all_finite_nonnegative=bool(n and len(values) == n and all(v >= 0 for v in values)),
                    role='template_values_not_verified_future_labels' if name == 'sample_submission' else 'historical_sales_target_values'))
                for group, mask in {
                    'NULL': [reason == 'missing' for _, reason in parsed], 'non_numeric': [reason == 'non_numeric' for _, reason in parsed],
                    'non_finite': [reason == 'non_finite' for _, reason in parsed], 'negative': [reason == 'finite' and v < 0 for v, reason in parsed]}.items():
                    exceptions[name + '_' + target + '_' + group] = bounded(frame, pd.Series(mask, index=frame.index, dtype=bool), EXPECTED, examples)
            evidence = hashlib.sha256()
            for i in range(n):
                hash_row(evidence, [i + 2, states.iloc[i], dates.iloc[i].date().isoformat() if valid.iloc[i] else None,
                                   *[[target, decimal_text(parsed_targets[target][i][0]), parsed_targets[target][i][1]] for target in TARGETS]])
            fingerprints[name] = evidence.hexdigest()
        historical, future = date_sets['sales'], date_sets['sample_submission']
        overlap = sorted(historical & future)
        distance = (min(future) - max(historical)).days if historical and future else None
        relationship = dict(shared_dates=len(overlap), historical_only_dates=len(historical - future), template_only_dates=len(future - historical),
                             date_ranges_overlap=bool(max(min(historical), min(future)) <= min(max(historical), max(future))) if historical and future else None,
                             history_to_forecast_start_days=distance, calendar_days_between_ranges=distance - 1 if distance is not None and distance > 0 else None,
                             forecast_starts_next_calendar_day=distance == 1 if distance is not None else None,
                             sample_dates_on_or_before_history_end=sum(d <= max(historical) for d in future) if historical else None,
                             all_template_rows_strictly_after_history=bool(future and len(future) == len(frames['sample_submission']) and min(future) > max(historical)) if historical else None,
                             column_names_equal=set(sample_submission.columns) == set(sales.columns), column_order_equal=list(sample_submission.columns) == list(sales.columns))
        metrics.update(relationship)
        exceptions['shared_calendar_dates'] = dict(cases=len(overlap), examples_reported=min(examples, len(overlap)), examples_omitted=max(0, len(overlap) - examples),
                                                  records=[dict(date=d.isoformat()) for d in overlap[:examples]])
        roundtrip, after_dtypes = inspect_roundtrip(frames['sample_submission'])
        before_dtypes = frames['sample_submission'].attrs.get('parsed_dtypes')
        schemas['sample_submission']['roundtrip_observed_parsed_dtypes'] = after_dtypes
        schemas['sample_submission']['roundtrip_observed_dtype_match'] = before_dtypes == after_dtypes if before_dtypes is not None else None
        reports = dict(column_profile=profiles, dates=date_reports, target_values=target_reports, date_steps=steps, leap_days=leap_records)
        checks = dict(date_states_partition_rows=all(r['null_rows'] + r['invalid_rows'] + r['valid_rows'] == r['rows'] for r in date_reports),
                      duplicate_accounting=all(r['distinct_dates'] + r['duplicate_excess'] == r['valid_rows'] for r in date_reports),
                      calendar_accounting=all(r['expected_calendar_days'] is None or r['expected_calendar_days'] == r['distinct_dates'] + r['missing_calendar_days'] for r in date_reports),
                      target_states_partition_rows=all(r['null_rows'] + r['non_numeric_rows'] + r['non_finite_rows'] + r['finite_rows'] == r['rows'] for r in target_reports),
                      target_signs_partition_finite_values=all(r['negative_rows'] + r['zero_rows'] + r['positive_rows'] == r['finite_rows'] for r in target_reports),
                      template_memory_roundtrip_preserves_structure_and_values=all(roundtrip[k] for k in ['column_order_preserved', 'row_count_preserved', 'ordered_date_lexemes_preserved', 'all_decoded_values_preserved']),
                      template_memory_roundtrip_observed_dtypes_match=before_dtypes is None or before_dtypes == after_dtypes)
        return dict(metrics=metrics, reports={name: pd.DataFrame(rows, columns=SCHEMAS[name]) for name, rows in reports.items()},
                    schemas=schemas, template_memory_roundtrip=roundtrip, ledger_fingerprints=fingerprints, exceptions=exceptions, checks=checks)
    return SimpleNamespace(
        argparse=argparse,
        calendar=calendar,
        csv=csv,
        hashlib=hashlib,
        io=io,
        re=re,
        sys=sys,
        Counter=Counter,
        date=date,
        datetime=datetime,
        timedelta=timedelta,
        timezone=timezone,
        Decimal=Decimal,
        InvalidOperation=InvalidOperation,
        Path=Path,
        pd=pd,
        digest=digest,
        equivalent=equivalent,
        number=number,
        bounded=bounded,
        decimal_text=decimal_text,
        hash_row=hash_row,
        normalized=normalized,
        null_kind=null_kind,
        read_sources=read_sources,
        strict_dates=strict_dates,
        missing_examples=missing_examples,
        NA_TOKENS=NA_TOKENS,
        is_identifier=is_identifier,
        ROOT=ROOT,
        EXPECTED=EXPECTED,
        TARGETS=TARGETS,
        TABLES=TABLES,
        SCHEMAS=SCHEMAS,
        table_fingerprint=table_fingerprint,
        inspect_roundtrip=inspect_roundtrip,
        target_pattern=target_pattern,
        analyze=analyze,
    )


@cache
def source_profiles():
    """Run selected GD1 profiles sequentially and reconcile with a CSV-reader audit."""

    import argparse
    import csv
    import hashlib
    import subprocess
    import sys
    from pathlib import Path

    import pandas as pd

    ROOT = table_reader().ROOT
    DATE_COLUMNS = table_reader().DATE_COLUMNS
    DATE_FORMATS = table_reader().DATE_FORMATS


    TABLES = ['customers', 'geography', 'inventory', 'orders', 'order_items',
              'payments', 'products', 'promotions', 'returns', 'reviews', 'sales',
              'sample_submission', 'shipments', 'web_traffic']
    # pandas default read_csv NA tokens, recorded explicitly for the independent audit.
    NA_TOKENS = {'', '#N/A', '#N/A N/A', '#NA', '-1.#IND', '-1.#QNAN', '-NaN',
                 '-nan', '1.#IND', '1.#QNAN', '<NA>', 'N/A', 'NA', 'NULL',
                 'NaN', 'None', 'n/a', 'nan', 'null'}


    def digest(path):
        with path.open('rb') as stream:
            return hashlib.file_digest(stream, 'sha256').hexdigest()
    return SimpleNamespace(
        argparse=argparse,
        csv=csv,
        hashlib=hashlib,
        subprocess=subprocess,
        sys=sys,
        Path=Path,
        pd=pd,
        ROOT=ROOT,
        DATE_COLUMNS=DATE_COLUMNS,
        DATE_FORMATS=DATE_FORMATS,
        TABLES=TABLES,
        NA_TOKENS=NA_TOKENS,
        digest=digest,
    )


@cache
def table_reader():
    """Read-only, single-table profiling. Run from repository root with python -m."""

    import argparse
    import csv
    import hashlib
    import re
    import sys
    from datetime import datetime, timezone
    from pathlib import Path

    import pandas as pd


    ROOT = PROJECT_ROOT
    DATE_COLUMNS = {
        'customers': ['signup_date'], 'inventory': ['snapshot_date'],
        'orders': ['order_date'], 'promotions': ['start_date', 'end_date'],
        'returns': ['return_date'], 'reviews': ['review_date'],
        'sales': ['Date'], 'sample_submission': ['Date'],
        'shipments': ['ship_date', 'delivery_date'], 'web_traffic': ['date'],
        'products': [], 'geography': [], 'order_items': [], 'payments': [],
    }
    DATE_FORMATS = {'customers': '%Y-%m-%d'}


    def is_identifier(name):
        """Dataset naming convention, not a claim about key constraints."""
        return name == 'zip' or bool(re.search(r'_id(?:_\d+)?$', name))


    def read_table(path, encoding='utf-8-sig', sep=','):
        """Validate CSV structure before pandas inference; never write to source."""
        with path.open(encoding=encoding, newline='') as stream:
            reader = csv.reader(stream, delimiter=sep, strict=True)
            header = next(reader, None)
            if not header or any(not name.strip() for name in header):
                raise ValueError('CSV is empty or contains unnamed columns.')
            if len(header) != len(set(header)):
                raise ValueError('CSV contains duplicate column names.')
            for row in reader:
                if len(row) != len(header):
                    raise ValueError(f'CSV line {reader.line_num}: expected {len(header)} fields, got {len(row)}.')
        identifiers = {name: 'string' for name in header if is_identifier(name)}
        return pd.read_csv(path, encoding=encoding, sep=sep, dtype=identifiers, low_memory=False,
                           skip_blank_lines=False, on_bad_lines='error')
    return SimpleNamespace(
        argparse=argparse,
        csv=csv,
        hashlib=hashlib,
        re=re,
        sys=sys,
        datetime=datetime,
        timezone=timezone,
        Path=Path,
        pd=pd,
        ROOT=ROOT,
        DATE_COLUMNS=DATE_COLUMNS,
        DATE_FORMATS=DATE_FORMATS,
        is_identifier=is_identifier,
        read_table=read_table,
    )


@cache
def business_metrics():
    """Business summaries inspired by Thu Luyn EDA; consume GD2, never publish data.

    Product quantities/concentration/trends: EDA cells 57–75 (one-based).
    Product Net rankings and segment breakdown: additions by the integrating team.
    Promotion quantity: EDA cell 86; reuse the existing NV06 order ledger.
    """

    from collections import Counter, defaultdict
    from decimal import Decimal
    import hashlib
    from pathlib import Path
    from statistics import mean, median, stdev

    import pandas as pd

    ITEMS_SCHEMA = preprocessing().ITEMS_SCHEMA
    read_processed = delivery().read_processed
    read_source_table = foundation().read_source_table


    def exact_cents(value):
        """Require observed finite Decimal money exactly representable in cents."""
        if not isinstance(value, Decimal) or not value.is_finite():
            raise ValueError('Money must be a finite observed Decimal')
        # Tuple conversion avoids caller Decimal precision and never rounds.
        sign, digits, exponent = value.as_tuple()
        coefficient = int(''.join(map(str, digits))) * (-1 if sign else 1)
        power = exponent + 2
        if power >= 0:
            return coefficient * 10 ** power
        divisor = 10 ** (-power)
        if coefficient % divisor:
            raise ValueError('Fractional cent: keep original precision and review')
        return coefficient // divisor


    def product_summary(item_rows, catalog):
        """Summarize source lines without deduplicating order/product pairs.

        Includes the complete current catalog. Zero is an observed transaction
        count in this complete ledger, never a claim about availability/lifecycle.
        Ties are ordered by string product_id for reproducible rankings.
        """
        metadata = {}
        for row in catalog:
            key = row['product_id']
            if not isinstance(key, str) or not key or key in metadata:
                raise ValueError('Catalog product_id must be unique nonempty strings')
            metadata[key] = {k: row[k] for k in ['product_id', 'product_name', 'category', 'segment']}
        if not metadata:
            raise ValueError('Empty catalog')
        counts = defaultdict(Counter)
        years = Counter()
        line_ids = set()
        order_ids = set()
        delivered_orders = set()
        dates = []
        for row in item_rows:
            key, line = row['product_id'], row['item_row_id']
            if key not in metadata:
                raise ValueError('Item has no catalog parent')
            if not isinstance(line, str) or not line or line in line_ids:
                raise ValueError('item_row_id must be unique nonempty strings')
            line_ids.add(line)
            order_ids.add(row['order_id'])
            quantity = row['quantity']
            if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
                raise ValueError('Expected positive integer quantity')
            money = {k: exact_cents(row['line_' + k]) for k in ['gross', 'discount', 'net']}
            if money['net'] != money['gross'] - money['discount']:
                raise ValueError('Line Net differs from Gross minus Discount')
            scopes = ['all']
            if row['order_status'] == 'delivered':
                scopes.append('delivered')
                delivered_orders.add(row['order_id'])
                date = row['order_date_parsed']
                if date is None:
                    raise ValueError('Missing order date')
                years[(key, date.year)] += quantity
            dates.append(row['order_date_parsed'])
            for scope in scopes:
                counts[key][scope + '_quantity'] += quantity
                counts[key][scope + '_lines'] += 1
                for metric, cents in money.items():
                    counts[key][scope + '_' + metric + '_cents'] += cents
        columns = [s + '_' + k for s in ['all', 'delivered'] for k in
                   ['quantity', 'lines', 'gross_cents', 'discount_cents', 'net_cents']]
        products = pd.DataFrame([{**metadata[key], **{c: counts[key][c] for c in columns}}
                                 for key in sorted(metadata)])
        ranked = products.sort_values(['delivered_quantity', 'product_id'], ascending=[False, True]).reset_index(drop=True)
        total = int(ranked.delivered_quantity.sum())
        ranked['cumulative_quantity'] = ranked.delivered_quantity.cumsum()
        # Integer threshold, including the crossing product. No float idxmax on an empty/all-zero series.
        crossing = next((i + 1 for i, v in enumerate(ranked.cumulative_quantity) if total > 0 and int(v) * 5 >= total * 4), None)
        ranked['cumulative_quantity_pct'] = 100 * ranked.cumulative_quantity / total if total else float('nan')
        ranked['catalog_pct'] = 100 * (ranked.index + 1) / len(ranked)
        active = products.delivered_quantity.gt(0)
        groups = {}
        for field in ['category', 'segment']:
            rows = []
            for label, frame in products.groupby(field, dropna=False, sort=True):
                n = int(frame.delivered_quantity.gt(0).sum())
                q = int(frame.delivered_quantity.sum())
                rows.append({field: label, 'catalog_products': len(frame), 'products_with_delivered': n,
                             'delivered_quantity': q, 'quantity_share_pct': 100 * q / total if total else None,
                             'mean_quantity_per_active_product': q / n if n else None,
                             **{metric: int(frame[metric].sum()) for metric in columns if metric.endswith('_cents')}})
            groups[field] = pd.DataFrame(rows).sort_values(['delivered_quantity', field], ascending=[False, True]).reset_index(drop=True)
        summary = dict(catalog_products=len(products), ordered_products=int(products.all_quantity.gt(0).sum()),
            delivered_products=int(active.sum()), no_order_products=int(products.all_quantity.eq(0).sum()),
            ordered_without_delivered=int((products.all_quantity.gt(0) & ~active).sum()),
            without_delivered=int((~active).sum()), item_rows=len(line_ids), orders=len(order_ids),
            delivered_orders=len(delivered_orders), products_for_80=crossing,
            **{c: int(products[c].sum()) for c in columns},
            date_start=str(min(dates)) if dates else None, date_end=str(max(dates)) if dates else None)
        trends = pd.DataFrame([dict(product_id=p, year=y, delivered_quantity=q) for (p, y), q in sorted(years.items())])
        return dict(products=products, ranked=ranked, categories=groups['category'], segments=groups['segment'],
                    trends=trends, summary=summary)


    def load_product_summary(root):
        """Đọc bảng dòng hàng GD2 theo schema và danh mục sản phẩm hiện tại."""
        root = Path(root)
        path = root / 'data/processed/order_items_common.csv'
        items_hash = file_sha(path)
        source = read_source_table('products', root=root)
        result = product_summary((dict(zip(ITEMS_SCHEMA, values)) for values in read_processed(path, ITEMS_SCHEMA)),
                                 source.working.to_dict('records'))
        if file_sha(path) != items_hash:
            raise ValueError('order_items_common.csv thay đổi trong lúc đọc')
        result['provenance'] = dict(items_sha256=items_hash, products_sha256=source.metadata['source_sha256'])
        return result


    def promotion_quantity_summary(orders):
        """Consume NV06's existing one-row/order ledger, without another JOIN.

        Required: order_id, _has_code (bool), _qty (integer), _net_c (integer cents),
        order_status. No missing promo flag is silently treated as False.
        """
        keys = set()
        grouped = {False: [], True: []}
        for row in orders:
            key = row['order_id']
            if key is None or key in keys:
                raise ValueError('Order key missing or duplicated')
            keys.add(key)
            flag = row['_has_code']
            if not isinstance(flag, bool):
                raise ValueError('Promotion presence must be a known boolean')
            for field in ['_qty', '_net_c']:
                if isinstance(row[field], bool) or not isinstance(row[field], int):
                    raise ValueError('Quantity and cent money must be integers')
            grouped[flag].append(row)
        result = []
        for flag, rows in grouped.items():
            quantities = [r['_qty'] for r in rows]
            n = len(rows)
            net = sum(r['_net_c'] for r in rows)
            delivered = sum(r['order_status'] == 'delivered' for r in rows)
            result.append(dict(has_code=flag, orders=n, quantity=sum(quantities),
                mean_quantity=mean(quantities) if n else None, median_quantity=median(quantities) if n else None,
                std_quantity=stdev(quantities) if n > 1 else None, net_cents=net,
                mean_net=net / (100 * n) if n else None,
                delivered_orders=delivered, delivered_rate_pct=100 * delivered / n if n else None))
        return pd.DataFrame(result)
    return SimpleNamespace(
        Counter=Counter,
        defaultdict=defaultdict,
        Decimal=Decimal,
        hashlib=hashlib,
        Path=Path,
        mean=mean,
        median=median,
        stdev=stdev,
        pd=pd,
        ITEMS_SCHEMA=ITEMS_SCHEMA,
        read_processed=read_processed,
        read_source_table=read_source_table,
        exact_cents=exact_cents,
        product_summary=product_summary,
        load_product_summary=load_product_summary,
        promotion_quantity_summary=promotion_quantity_summary,
    )


@cache
def preprocessing():
    """Bounded-memory common views. SQLite is temporary; money is always Decimal text."""

    from collections import Counter
    import csv
    from decimal import Decimal
    from itertools import repeat
    from pathlib import Path
    import sqlite3
    import tempfile

    import pandas as pd

    TOLERANCE = v02().TOLERANCE
    digest = v02().digest
    null_kind = v06().null_kind
    TABLES = contracts().TABLES
    CONTRACT_VERSION = contracts().CONTRACT_VERSION
    DataValidationError = foundation().DataValidationError
    SourceStructureError = foundation().SourceStructureError
    exact_sum = foundation().exact_sum
    exact_product = foundation().exact_product
    iter_source_chunks = foundation().iter_source_chunks
    resolve_project_root = foundation().resolve_project_root


    ORDERS_SCHEMA = dict(zip(
        (*TABLES['orders'].required_columns, 'order_date_parsed', 'signup_date_parsed',
         'item_rows', 'quantity_total', 'payment_rows', 'return_rows', 'returned_quantity',
         'shipment_rows', 'gross_amount', 'discount_amount_total', 'net_amount',
         'payment_amount', 'refund_amount_observed', 'cogs_check_amount',
         'order_before_signup_flag', 'items_repeated_pair_flag', 'multiple_return_records_flag',
         'delivered_missing_shipment_flag', 'returned_missing_return_detail_flag',
         'refund_gt_payment_flag', 'refund_gt_payment_over_tolerance_flag', 'order_source_row_id'),
        (*(['string'] * 8), 'date', 'date', *(['integer'] * 6), *(['decimal'] * 6),
         *(['boolean'] * 7), 'string')))
    ITEMS_SCHEMA = {
        'order_id': 'string', 'product_id': 'string', 'quantity': 'integer',
        'unit_price': 'decimal', 'discount_amount': 'decimal', 'promo_id': 'string',
        'promo_id_2': 'string', 'item_row_id': 'string', 'order_date': 'string',
        'order_date_parsed': 'date', 'order_status': 'string', 'product_name': 'string',
        'category': 'string', 'segment': 'string', 'product_cogs_reference': 'decimal',
        'line_gross': 'decimal', 'line_discount': 'decimal', 'line_net': 'decimal',
        'line_cogs_check': 'decimal',
    }


    def quote(name):
        return '"' + name.replace('"', '""') + '"'


    def difference(a, b):
        return None if a is None or b is None else exact_sum((Decimal(a), exact_product(-1, Decimal(b))))


    def _multiply(a, b):
        return None if a is None or b is None else str(exact_product(Decimal(a), Decimal(b)))


    def _subtract(a, b):
        value = difference(a, b)
        return None if value is None else str(value)


    def _greater(a, b, tolerance='0'):
        value = difference(a, b)
        return None if value is None else int(value > Decimal(tolerance))


    class _Sum:
        strict = True

        def __init__(self):
            self.value = Decimal(0)
            self.missing = False
            self.seen = False

        def step(self, value):
            if value is None:
                self.missing = True
            else:
                self.seen = True
                self.value = exact_sum((self.value, Decimal(value)))

        def finalize(self):
            return None if not self.seen or (self.strict and self.missing) else str(self.value)


    class _ObservedSum(_Sum):
        strict = False


    def typed_value(value, kind):
        if value is None:
            return None
        if kind == 'decimal':
            number = Decimal(str(value))
            if not number.is_finite():
                raise ValueError('Non-finite processed money')
            return number
        if kind == 'integer':
            number = Decimal(str(value))
            if number != number.to_integral_value() or not -(2**63) <= number < 2**63:
                raise ValueError('Invalid processed integer')
            return int(number)
        if kind == 'boolean':
            if value not in (0, 1, '0', '1', 'True', 'False'):
                raise ValueError('Invalid processed boolean')
            return value in (1, '1', 'True')
        if kind == 'date':
            return pd.Timestamp(value)
        return str(value)


    class CommonView:
        """A typed table streamed from the temporary store, never an implicit full load."""

        def __init__(self, run, table, schema):
            self.run, self.table, self.schema = run, table, dict(schema)

        def __len__(self):
            return self.run.scalar(f'SELECT COUNT(*) FROM {quote(self.table)}')

        def rows(self, limit=None):
            sql = f'SELECT {",".join(map(quote, self.schema))} FROM {quote(self.table)} ORDER BY _record'
            if limit is not None:
                sql += f' LIMIT {int(limit)}'
            for row in self.run.connection.execute(sql):
                yield tuple(typed_value(value, kind) for value, kind in zip(row, self.schema.values()))

        def iter_frames(self, chunk_size=25000):
            batch = []
            for row in self.rows():
                batch.append(row)
                if len(batch) == chunk_size:
                    yield self._frame(batch)
                    batch = []
            if batch:
                yield self._frame(batch)

        def _frame(self, rows):
            frame = pd.DataFrame(rows, columns=self.schema)
            for col, kind in self.schema.items():
                if kind in {'integer', 'boolean', 'string'}:
                    frame[col] = frame[col].astype({'integer': 'Int64', 'boolean': 'boolean', 'string': 'string'}[kind])
                elif kind == 'date':
                    frame[col] = pd.to_datetime(frame[col])
            return frame

        def head(self, n=8):
            return self._frame(list(self.rows(limit=n)))

        def observed_sum(self, column):
            if self.schema[column] not in {'integer', 'decimal'}:
                raise ValueError('Not an additive numeric field')
            value = self.run.scalar(f'SELECT OBS_SUM({quote(column)}) FROM {quote(self.table)}')
            return typed_value(value, self.schema[column])


    class CommonPreprocessing:
        """Context-managed staging store. No raw/source/processed file is modified here."""

        def __init__(self, root=None, *, chunk_size=25000):
            self.root = resolve_project_root(root)
            self.chunk_size = chunk_size
            self._temp = tempfile.TemporaryDirectory(prefix='retail_gd2_')
            self.connection = sqlite3.connect(str(Path(self._temp.name) / 'staging.sqlite'))
            self.connection.execute('PRAGMA journal_mode=OFF')
            self.connection.execute('PRAGMA synchronous=OFF')
            self.connection.execute('PRAGMA temp_store=FILE')
            self.connection.execute('PRAGMA cache_size=-16384')
            self.connection.create_function('MUL', 2, _multiply)
            self.connection.create_function('SUB', 2, _subtract)
            self.connection.create_function('GT', 3, _greater)
            self.connection.create_function('NK', 1, lambda x: None if null_kind(x) != 'non_null' or not str(x).strip() else x)
            self.connection.create_aggregate('ESUM', 1, _Sum)
            self.connection.create_aggregate('OBS_SUM', 1, _ObservedSum)
            self.sources, self.checks, self.views = {}, [], {}
            self.report = {'contract_version': CONTRACT_VERSION, 'sources': self.sources, 'checks': self.checks}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.close()

        def close(self):
            self.connection.close()
            self._temp.cleanup()

        def scalar(self, sql, params=()):
            return self.connection.execute(sql, params).fetchone()[0]

        def check(self, name, ok, *, details=None):
            self.checks.append({'check': name, 'status': 'passed' if ok else 'unsafe', 'details': details})
            if not ok:
                raise ValueError(f'Unsafe preprocessing: {name}: {details}')

        def load(self, *, names=None, progress=None):
            for name in names if names is not None else TABLES:
                spec = TABLES[name]
                parsed = [c for c in spec.columns if c.kind != 'string']
                columns = [*spec.required_columns, *(f'_p_{c.name}' for c in parsed), '_record', '_source_row_id']
                self.connection.execute(f'CREATE TABLE {quote(name)} ({",".join(quote(c)+" TEXT" for c in columns)})')
                placeholders = ','.join('?' for _ in columns)
                count, states = 0, Counter()
                for chunk in iter_source_chunks(name, root=self.root, chunk_size=self.chunk_size):
                    unsafe = [c for c in chunk.checks if c.status == 'unsafe']
                    if unsafe:
                        raise DataValidationError(unsafe)
                    for c in chunk.checks:
                        states[(c.columns[0], c.status, c.code)] += len(c.record_indices)
                    records = []
                    working_rows = (chunk.working[[c.name for c in parsed]].itertuples(index=False, name=None)
                                    if parsed else repeat((), len(chunk.raw)))
                    for raw, working, index, row_id in zip(
                            chunk.raw.itertuples(index=False, name=None),
                            working_rows,
                            chunk.lineage.source_record_index, chunk.lineage.source_row_id):
                        values = []
                        for value, col in zip(working, parsed):
                            values.append(None if pd.isna(value) else value.date().isoformat()
                                          if col.kind == 'date' else str(value))
                        records.append((*raw, *values, str(index), row_id))
                    self.check('stream_cardinality:'+name, len(records)==len(chunk.raw))
                    self.connection.executemany(f'INSERT INTO {quote(name)} VALUES ({placeholders})', records)
                    count += len(records)
                    self.connection.commit()
                source_hash = digest(self.root / 'data/raw' / f'{name}.csv')
                self.sources[name] = dict(path=f'data/raw/{name}.csv', sha256=source_hash, rows=count,
                                          columns=list(spec.required_columns),
                                          states=[dict(column=c, status=s, state=k, rows=n) for (c,s,k),n in states.items()])
                for i, keys in enumerate(spec.keys):
                    keycols = [f'_p_{c}' if any(x.name == c and x.kind != 'string' for x in spec.columns) else c for c in keys]
                    try:
                        self.connection.execute(f'CREATE UNIQUE INDEX {quote(name+"_key_"+str(i))} ON {quote(name)} ({",".join(map(quote,keycols))})')
                    except sqlite3.IntegrityError as exc:
                        raise SourceStructureError(f'{name}: duplicate global key {keys}; no deduplication') from exc
                if 'order_id' in spec.required_columns and spec.keys != (('order_id',),):
                    self.connection.execute(f'CREATE INDEX {quote(name+"_order")} ON {quote(name)} (order_id)')
                if name == 'order_items':
                    self.connection.execute('CREATE INDEX item_pairs ON order_items(order_id,product_id)')
                if name == 'orders':
                    self.connection.execute('CREATE INDEX orders_customer ON orders(customer_id)')
                if progress:
                    progress(name, count)
            self._foreign_keys()
            if 'inventory' in self.sources:
                bad = self.scalar("SELECT COUNT(*) FROM inventory WHERE CAST(_p_year AS INTEGER) != CAST(substr(_p_snapshot_date,1,4) AS INTEGER) OR CAST(_p_month AS INTEGER) != CAST(substr(_p_snapshot_date,6,2) AS INTEGER)")
                self.check('inventory_period_metadata', bad == 0, details=bad)
            self.check_sources()
            return self

        def _foreign_keys(self):
            for name in self.sources:
                for fk in TABLES[name].foreign_keys:
                    if fk.parent_table not in self.sources:
                        raise ValueError(f'Unknown FK: {name} -> {fk.parent_table}; parent not loaded')
                    equality = ' AND '.join(f'p.{quote(b)}=c.{quote(a)}' for a,b in zip(fk.columns,fk.parent_columns))
                    active = ' AND '.join(f'NK(c.{quote(a)}) IS NOT NULL' for a in fk.columns)
                    bad = self.scalar(f'SELECT COUNT(*) FROM {quote(name)} c WHERE ({active}) AND NOT EXISTS (SELECT 1 FROM {quote(fk.parent_table)} p WHERE {equality})')
                    self.check(f'FK:{name}:{",".join(fk.columns)}->{fk.parent_table}', bad == 0, details=bad)

        def check_sources(self):
            for name, source in self.sources.items():
                self.check(f'source_hash:{name}', digest(self.root/source['path']) == source['sha256'])

        def build_orders_common(self):
            db = self.connection
            db.executescript('''
            CREATE TABLE _line_amounts AS
              SELECT i._record,i.order_id,i._p_quantity AS quantity,p._p_cogs AS product_cogs_reference,
                MUL(i._p_quantity,i._p_unit_price) AS line_gross,i._p_discount_amount AS line_discount,
                SUB(MUL(i._p_quantity,i._p_unit_price),i._p_discount_amount) AS line_net,
                MUL(i._p_quantity,p._p_cogs) AS line_cogs_check
              FROM order_items i LEFT JOIN products p ON i.product_id=p.product_id;
            CREATE UNIQUE INDEX line_record ON _line_amounts(_record);
            CREATE INDEX line_orders ON _line_amounts(order_id);
            CREATE TABLE _item_totals AS SELECT order_id,COUNT(*) AS item_rows,
              ESUM(quantity) AS quantity_total,ESUM(line_gross) AS gross,
              ESUM(line_discount) AS discount,ESUM(line_net) AS net,
              ESUM(line_cogs_check) AS cogs FROM _line_amounts GROUP BY order_id;
            CREATE UNIQUE INDEX item_total_key ON _item_totals(order_id);
            CREATE TABLE _repeat_item_orders AS SELECT DISTINCT order_id FROM
              (SELECT order_id,product_id FROM order_items GROUP BY order_id,product_id HAVING COUNT(*)>1);
            CREATE UNIQUE INDEX repeat_key ON _repeat_item_orders(order_id);
            CREATE TABLE _pay_totals AS SELECT order_id,COUNT(*) AS n,ESUM(_p_payment_value) AS amount FROM payments GROUP BY order_id;
            CREATE UNIQUE INDEX pay_total_key ON _pay_totals(order_id);
            CREATE TABLE _return_totals AS SELECT order_id,COUNT(*) AS n,ESUM(_p_return_quantity) AS quantity,
              ESUM(_p_refund_amount) AS amount FROM returns GROUP BY order_id;
            CREATE UNIQUE INDEX return_total_key ON _return_totals(order_id);
            CREATE TABLE _ship_totals AS SELECT order_id,COUNT(*) AS n FROM shipments GROUP BY order_id;
            CREATE UNIQUE INDEX ship_total_key ON _ship_totals(order_id);
            ''')
            original = ','.join(f'o.{quote(c)}' for c in TABLES['orders'].required_columns)
            db.execute(f'''CREATE TABLE _orders_common AS SELECT {original},
              o._p_order_date AS order_date_parsed,c._p_signup_date AS signup_date_parsed,
              COALESCE(i.item_rows,0) AS item_rows,i.quantity_total,
              COALESCE(p.n,0) AS payment_rows,COALESCE(r.n,0) AS return_rows,r.quantity AS returned_quantity,
              COALESCE(s.n,0) AS shipment_rows,i.gross AS gross_amount,i.discount AS discount_amount_total,
              i.net AS net_amount,p.amount AS payment_amount,r.amount AS refund_amount_observed,i.cogs AS cogs_check_amount,
              CASE WHEN o._p_order_date IS NULL OR c._p_signup_date IS NULL THEN NULL ELSE o._p_order_date<c._p_signup_date END AS order_before_signup_flag,
              (rep.order_id IS NOT NULL) AS items_repeated_pair_flag,(COALESCE(r.n,0)>1) AS multiple_return_records_flag,
              CASE WHEN NK(o.order_status) IS NULL THEN NULL ELSE (o.order_status='delivered' AND COALESCE(s.n,0)=0) END AS delivered_missing_shipment_flag,
              CASE WHEN NK(o.order_status) IS NULL THEN NULL ELSE (o.order_status='returned' AND COALESCE(r.n,0)=0) END AS returned_missing_return_detail_flag,
              GT(r.amount,p.amount,'0') AS refund_gt_payment_flag,
              GT(r.amount,p.amount,'{TOLERANCE}') AS refund_gt_payment_over_tolerance_flag,
              o._source_row_id AS order_source_row_id,CAST(o._record AS INTEGER) AS _record
              FROM orders o LEFT JOIN customers c ON o.customer_id=c.customer_id
              LEFT JOIN _item_totals i ON o.order_id=i.order_id
              LEFT JOIN _pay_totals p ON o.order_id=p.order_id
              LEFT JOIN _return_totals r ON o.order_id=r.order_id
              LEFT JOIN _ship_totals s ON o.order_id=s.order_id
              LEFT JOIN _repeat_item_orders rep ON o.order_id=rep.order_id''')
            db.execute('CREATE UNIQUE INDEX common_order_key ON _orders_common(order_id)')
            self.views['orders_common'] = CommonView(self, '_orders_common', ORDERS_SCHEMA)
            self.connection.commit()
            return self.views['orders_common']

        def build_order_items_common(self):
            self.connection.execute('''CREATE VIEW _order_items_common AS SELECT
              i.order_id,i.product_id,i._p_quantity AS quantity,i._p_unit_price AS unit_price,
              i._p_discount_amount AS discount_amount,NK(i.promo_id) AS promo_id,NK(i.promo_id_2) AS promo_id_2,
              i._source_row_id AS item_row_id,o.order_date,o._p_order_date AS order_date_parsed,o.order_status,
              p.product_name,p.category,p.segment,l.product_cogs_reference,l.line_gross,l.line_discount,l.line_net,l.line_cogs_check,
              CAST(i._record AS INTEGER) AS _record
              FROM order_items i LEFT JOIN orders o ON i.order_id=o.order_id
              LEFT JOIN products p ON i.product_id=p.product_id
              LEFT JOIN _line_amounts l ON i._record=l._record''')
            self.views['order_items_common'] = CommonView(self, '_order_items_common', ITEMS_SCHEMA)
            return self.views['order_items_common']

        def lineage_for_order(self, order_id):
            rows = []
            for name in ['orders', 'order_items', 'payments', 'returns', 'shipments']:
                for record, row_id in self.connection.execute(f'SELECT _record,_source_row_id FROM {quote(name)} WHERE order_id=?', (order_id,)):
                    rows.append(dict(table=name, source_record_index=int(record), source_row_id=row_id,
                                     source_sha256=self.sources[name]['sha256']))
            for name,sql in [('customers','SELECT c._record,c._source_row_id FROM orders o JOIN customers c ON o.customer_id=c.customer_id WHERE o.order_id=?'),
                             ('products','SELECT DISTINCT p._record,p._source_row_id FROM order_items i JOIN products p ON i.product_id=p.product_id WHERE i.order_id=?')]:
                for record,row_id in self.connection.execute(sql,(order_id,)):
                    rows.append(dict(table=name,source_record_index=int(record),source_row_id=row_id,
                                     source_sha256=self.sources[name]['sha256']))
            return rows

        def independent_source_totals(self):
            """CSV/Decimal scalar audit; no SQL/groupby or processed data as oracle."""
            def records(name):
                with (self.root/self.sources[name]['path']).open(encoding='utf-8-sig', newline='') as f:
                    yield from csv.DictReader(f)
            products = {r['product_id']: Decimal(r['cogs']) for r in records('products')}
            totals = dict.fromkeys(['quantity','gross','discount','net','payment','refund','returned_quantity','cogs'], Decimal(0))
            for r in records('order_items'):
                # Unknown totals cannot be declared complete. The staged validator
                # separately reports unknown fields rather than filling them with 0.
                try:
                    q,price,disc = (Decimal(r[c]) for c in ['quantity','unit_price','discount_amount'])
                except Exception as exc:
                    raise ValueError('Independent audit unavailable: item amount missing/invalid') from exc
                for key,value in [('quantity',q),('gross',exact_product(q,price)),('discount',disc),('cogs',exact_product(q,products[r['product_id']]))]:
                    totals[key] = exact_sum((totals[key], value))
            totals['net'] = difference(str(totals['gross']), str(totals['discount']))
            for name, columns in [('payments', [('payment_value','payment')]),
                                  ('returns',[('refund_amount','refund'),('return_quantity','returned_quantity')])]:
                for r in records(name):
                    for source,key in columns:
                        totals[key] = exact_sum((totals[key], Decimal(r[source])))
            return totals
    return SimpleNamespace(
        Counter=Counter,
        csv=csv,
        Decimal=Decimal,
        repeat=repeat,
        Path=Path,
        sqlite3=sqlite3,
        tempfile=tempfile,
        pd=pd,
        TOLERANCE=TOLERANCE,
        digest=digest,
        null_kind=null_kind,
        TABLES=TABLES,
        CONTRACT_VERSION=CONTRACT_VERSION,
        DataValidationError=DataValidationError,
        SourceStructureError=SourceStructureError,
        exact_sum=exact_sum,
        exact_product=exact_product,
        iter_source_chunks=iter_source_chunks,
        resolve_project_root=resolve_project_root,
        ORDERS_SCHEMA=ORDERS_SCHEMA,
        ITEMS_SCHEMA=ITEMS_SCHEMA,
        quote=quote,
        difference=difference,
        typed_value=typed_value,
        CommonView=CommonView,
        CommonPreprocessing=CommonPreprocessing,
    )


@cache
def contracts():
    """Declarative input contracts; snapshot observations are not business rules."""

    from dataclasses import dataclass
    from types import MappingProxyType
    from typing import Literal


    CONTRACT_VERSION = "2.3.1.3-v1"
    Kind = Literal["string", "integer", "decimal", "date"]
    NullPolicy = Literal["allowed", "unverified"]


    @dataclass(frozen=True)
    class ColumnSpec:
        name: str
        kind: Kind = "string"
        null_policy: NullPolicy = "unverified"
        date_format: str | None = None


    @dataclass(frozen=True)
    class ForeignKeySpec:
        columns: tuple[str, ...]
        parent_table: str
        parent_columns: tuple[str, ...]
        nullable: bool = False
        parent_unique: bool = True


    @dataclass(frozen=True)
    class TableSpec:
        name: str
        grain: str
        columns: tuple[ColumnSpec, ...]
        keys: tuple[tuple[str, ...], ...] = ()
        foreign_keys: tuple[ForeignKeySpec, ...] = ()
        repeatable_pairs: tuple[tuple[str, ...], ...] = ()
        snapshot_unique_keys: tuple[tuple[str, ...], ...] = ()
        dq_codes: tuple[str, ...] = ()

        @property
        def required_columns(self) -> tuple[str, ...]:
            return tuple(column.name for column in self.columns)


    def _columns(names, *, integers=(), decimals=(), dates=None, nullable=()):
        dates = dates or {}
        return tuple(
            ColumnSpec(name,
                       "date" if name in dates else "integer" if name in integers
                       else "decimal" if name in decimals else "string",
                       "allowed" if name in nullable else "unverified", dates.get(name))
            for name in names.split()
        )


    def _fk(column, parent, *, nullable=False):
        return ForeignKeySpec((column,), parent, (column,), nullable)


    def _dq(*numbers):
        return tuple(f"DQ-{number:02d}" for number in numbers)


    TABLES = MappingProxyType({
        "customers": TableSpec(
            "customers", "customer record",
            _columns("customer_id zip city signup_date gender age_group acquisition_channel",
                     dates={"signup_date": "%Y-%m-%d"}),
            keys=(("customer_id",),), foreign_keys=(_fk("zip", "geography"),),
            dq_codes=_dq(1, 2, 3, 19, 20, 21, 24)),
        "geography": TableSpec(
            "geography", "ZIP reference record", _columns("zip city region district"),
            keys=(("zip",),), dq_codes=_dq(24)),
        "orders": TableSpec(
            "orders", "order",
            _columns("order_id order_date customer_id zip order_status payment_method device_type order_source",
                     dates={"order_date": "%Y-%m-%d"}),
            keys=(("order_id",),),
            foreign_keys=(_fk("customer_id", "customers"), _fk("zip", "geography")),
            dq_codes=_dq(1, 2, 5, 6, 8, 9, 10, 11, 12, 18, 20, 21, 24)),
        "order_items": TableSpec(
            "order_items", "source item record; order-product pairs may repeat",
            _columns("order_id product_id quantity unit_price discount_amount promo_id promo_id_2",
                     integers=("quantity",), decimals=("unit_price", "discount_amount"),
                     nullable=("promo_id", "promo_id_2")),
            foreign_keys=(_fk("order_id", "orders"), _fk("product_id", "products"),
                          ForeignKeySpec(("promo_id",), "promotions", ("promo_id",), True),
                          ForeignKeySpec(("promo_id_2",), "promotions", ("promo_id",), True)),
            repeatable_pairs=(("order_id", "product_id"),),
            dq_codes=_dq(4, 6, 7, 8, 9, 13, 17, 18, 21, 24)),
        "payments": TableSpec(
            "payments", "source payment record; aggregate before order join",
            _columns("order_id payment_method payment_value installments",
                     integers=("installments",), decimals=("payment_value",)),
            foreign_keys=(_fk("order_id", "orders"),),
            snapshot_unique_keys=(("order_id",),), dq_codes=_dq(6, 12, 24)),
        "products": TableSpec(
            "products", "product reference record; historical validity unverified",
            _columns("product_id product_name category segment size color price cogs",
                     decimals=("price", "cogs")),
            keys=(("product_id",),), dq_codes=_dq(7, 8, 13, 24)),
        "promotions": TableSpec(
            "promotions", "promotion description",
            _columns("promo_id promo_name promo_type discount_value start_date end_date applicable_category promo_channel stackable_flag min_order_value",
                     integers=("stackable_flag",), decimals=("discount_value", "min_order_value"),
                     dates={"start_date": "%Y-%m-%d", "end_date": "%Y-%m-%d"},
                     nullable=("applicable_category",)),
            keys=(("promo_id",),), dq_codes=_dq(2, 4, 17, 18, 19, 20, 24)),
        "returns": TableSpec(
            "returns", "return record; order-product pairs may repeat",
            _columns("return_id order_id product_id return_date return_reason return_quantity refund_amount",
                     integers=("return_quantity",), decimals=("refund_amount",),
                     dates={"return_date": "%Y-%m-%d"}),
            keys=(("return_id",),),
            foreign_keys=(_fk("order_id", "orders"), _fk("product_id", "products"),
                          ForeignKeySpec(("order_id", "product_id"), "order_items",
                                         ("order_id", "product_id"), parent_unique=False)),
            repeatable_pairs=(("order_id", "product_id"),),
            dq_codes=_dq(2, 9, 11, 12, 15, 20, 24)),
        "shipments": TableSpec(
            "shipments", "source shipment record; warehouse/system identifier unverified",
            _columns("order_id ship_date delivery_date shipping_fee",
                     decimals=("shipping_fee",),
                     dates={"ship_date": "%Y-%m-%d", "delivery_date": "%Y-%m-%d"}),
            foreign_keys=(_fk("order_id", "orders"),),
            snapshot_unique_keys=(("order_id",),), dq_codes=_dq(2, 10, 20, 24)),
        "reviews": TableSpec(
            "reviews", "review record",
            _columns("review_id order_id product_id customer_id review_date rating review_title",
                     integers=("rating",), dates={"review_date": "%Y-%m-%d"}),
            keys=(("review_id",),),
            foreign_keys=(_fk("order_id", "orders"), _fk("product_id", "products"),
                          _fk("customer_id", "customers"),
                          ForeignKeySpec(("order_id", "product_id"), "order_items",
                                         ("order_id", "product_id"), parent_unique=False),
                          ForeignKeySpec(("order_id", "customer_id"), "orders",
                                         ("order_id", "customer_id"))),
            dq_codes=_dq(2, 20, 24)),
        "inventory": TableSpec(
            "inventory", "observed product-snapshot; warehouse scope unverified",
            _columns("snapshot_date product_id stock_on_hand units_received units_sold stockout_days days_of_supply fill_rate stockout_flag overstock_flag reorder_flag sell_through_rate product_name category segment year month",
                     integers=("stock_on_hand", "units_received", "units_sold", "stockout_days",
                               "stockout_flag", "overstock_flag", "reorder_flag", "year", "month"),
                     decimals=("days_of_supply", "fill_rate", "sell_through_rate"),
                     dates={"snapshot_date": "%Y-%m-%d"}),
            keys=(("product_id", "snapshot_date"), ("product_id", "year", "month")),
            foreign_keys=(_fk("product_id", "products"),),
            dq_codes=_dq(2, 13, 14, 15, 16, 20, 24)),
        "web_traffic": TableSpec(
            "web_traffic", "daily aggregate; no session-customer-order bridge",
            _columns("date sessions unique_visitors page_views bounce_rate avg_session_duration_sec traffic_source",
                     integers=("sessions", "unique_visitors", "page_views"),
                     decimals=("bounce_rate", "avg_session_duration_sec"),
                     dates={"date": "%Y-%m-%d"}),
            keys=(("date",),), dq_codes=_dq(2, 19, 20, 24)),
        "sales": TableSpec(
            "sales", "observed daily Revenue and COGS",
            _columns("Date Revenue COGS", decimals=("Revenue", "COGS"),
                     dates={"Date": "%Y-%m-%d"}),
            keys=(("Date",),), dq_codes=_dq(2, 6, 7, 20, 22, 24)),
        "sample_submission": TableSpec(
            "sample_submission", "output calendar/schema; target values are examples, not labels",
            _columns("Date Revenue COGS", decimals=("Revenue", "COGS"),
                     dates={"Date": "%Y-%m-%d"}),
            keys=(("Date",),), dq_codes=_dq(2, 20, 22, 24)),
    })
    return SimpleNamespace(
        dataclass=dataclass,
        MappingProxyType=MappingProxyType,
        Literal=Literal,
        CONTRACT_VERSION=CONTRACT_VERSION,
        Kind=Kind,
        NullPolicy=NullPolicy,
        ColumnSpec=ColumnSpec,
        ForeignKeySpec=ForeignKeySpec,
        TableSpec=TableSpec,
        TABLES=TABLES,
    )


@cache
def delivery():
    """Acceptance, supporting evidence, exact CSV round-trip and exclusive publication."""

    import csv
    from decimal import Decimal
    import hashlib
    import os
    from pathlib import Path
    import platform
    import tempfile

    import pandas as pd

    digest = v02().digest
    read_sources = v06().read_sources
    submission_analysis = v09().analyze
    quote = preprocessing().quote
    typed_value = preprocessing().typed_value


    NULL_TOKEN = r'\N'


    def validate_orders(run):
        view = run.views['orders_common']
        run.check('orders:row_count', len(view) == run.sources['orders']['rows'])
        run.check('orders:unique_key', run.scalar('SELECT COUNT(DISTINCT order_id) FROM _orders_common') == len(view))
        original_diff = ' OR '.join(f'o.{quote(c)} IS NOT v.{quote(c)}' for c in run.sources['orders']['columns'])
        run.check('orders:eight_source_columns', run.scalar(f'SELECT COUNT(*) FROM orders o JOIN _orders_common v ON o.order_id=v.order_id WHERE {original_diff}') == 0)
        before = dict(run.connection.execute('SELECT order_status,COUNT(*) FROM orders GROUP BY order_status'))
        after = dict(run.connection.execute('SELECT order_status,COUNT(*) FROM _orders_common GROUP BY order_status'))
        run.check('orders:status_distribution', before == after)
        for column, source in [('item_rows','order_items'),('payment_rows','payments'),('return_rows','returns'),('shipment_rows','shipments')]:
            run.check('orders:count:'+column, view.observed_sum(column) == run.sources[source]['rows'])
        conditions = [
            'item_rows>0 AND (gross_amount IS NULL OR discount_amount_total IS NULL OR net_amount IS NULL OR quantity_total IS NULL OR cogs_check_amount IS NULL)',
            'payment_rows>0 AND payment_amount IS NULL',
            'return_rows>0 AND (refund_amount_observed IS NULL OR returned_quantity IS NULL)',
            'order_date_parsed IS NULL',
        ]
        unavailable = run.scalar('SELECT COUNT(*) FROM _orders_common WHERE '+' OR '.join('('+x+')' for x in conditions))
        cross = []
        for returned, has_return in [(True,True),(True,False),(False,True),(False,False)]:
            n = run.scalar('SELECT COUNT(*) FROM _orders_common WHERE NK(order_status) IS NOT NULL AND (order_status=?)=? AND (return_rows>0)=?', ('returned',int(returned),int(has_return)))
            cross.append(dict(returned=returned, has_return_record=has_return, orders=n))
        flags = {}
        for col in list(view.schema)[22:29]:
            flags[col] = dict(true=run.scalar(f'SELECT COUNT(*) FROM _orders_common WHERE {quote(col)}=1'),
                              false=run.scalar(f'SELECT COUNT(*) FROM _orders_common WHERE {quote(col)}=0'),
                              unknown=run.scalar(f'SELECT COUNT(*) FROM _orders_common WHERE {quote(col)} IS NULL'))
        run.check('orders:DQ11_partition', sum(r['orders'] for r in cross) + run.scalar('SELECT COUNT(*) FROM _orders_common WHERE NK(order_status) IS NULL') == len(view))
        # Empty children must remain NULL money, not a technical zero.
        for count,money in [('item_rows','gross_amount'),('payment_rows','payment_amount'),('return_rows','refund_amount_observed')]:
            run.check('orders:missing_child:'+money, run.scalar(f'SELECT COUNT(*) FROM _orders_common WHERE {count}=0 AND {money} IS NOT NULL') == 0)
        report = dict(rows=len(view), columns=list(view.schema), status_distribution=before,
                      dq11_cross=cross, flags=flags, unavailable_orders=unavailable,
                      accepted=unavailable == 0,
                      totals={c:view.observed_sum(c) for c,k in view.schema.items() if k in {'integer','decimal'}})
        run.report['orders_common'] = report
        return report


    def validate_items(run):
        orders,items = run.views['orders_common'],run.views['order_items_common']
        run.check('items:row_count', len(items) == run.sources['order_items']['rows'])
        run.check('items:unique_id', run.scalar('SELECT COUNT(DISTINCT item_row_id) FROM _order_items_common') == len(items))
        run.check('items:no_order_money', not {'payment_amount','refund_amount_observed'}.intersection(items.schema))
        unavailable = run.scalar('SELECT COUNT(*) FROM _order_items_common WHERE line_gross IS NULL OR line_discount IS NULL OR line_net IS NULL OR line_cogs_check IS NULL')
        for line,order in [('quantity','quantity_total'),('line_gross','gross_amount'),('line_discount','discount_amount_total'),('line_net','net_amount'),('line_cogs_check','cogs_check_amount')]:
            run.check('items:conservation:'+line, items.observed_sum(line) == orders.observed_sum(order))
        # Check the actual per-order values too, not only coincidentally equal global sums.
        bad = run.scalar('''SELECT COUNT(*) FROM _item_totals i JOIN _orders_common o ON i.order_id=o.order_id
           WHERE i.gross IS NOT o.gross_amount OR i.discount IS NOT o.discount_amount_total
           OR i.net IS NOT o.net_amount OR i.cogs IS NOT o.cogs_check_amount''')
        run.check('items:per_order_conservation', bad == 0)
        run.report['order_items_common'] = dict(rows=len(items), columns=list(items.schema), accepted=unavailable==0,
            unavailable_rows=unavailable, totals={c:items.observed_sum(c) for c,k in items.schema.items() if k in {'integer','decimal'}})
        return run.report['order_items_common']


    def validate_financials(run):
        totals = run.independent_source_totals()
        mapping = dict(quantity='quantity_total',gross='gross_amount',discount='discount_amount_total',net='net_amount',
                       payment='payment_amount',refund='refund_amount_observed',returned_quantity='returned_quantity',cogs='cogs_check_amount')
        for source,col in mapping.items():
            actual = run.views['orders_common'].observed_sum(col)
            # Zero source return rows has no observed monetary total; do not synthesize it.
            expected = None if source in {'refund','returned_quantity'} and run.sources['returns']['rows']==0 else totals[source]
            run.check('financial:independent_csv:'+source, actual == expected, details=dict(actual=actual,expected=expected))
        run.report['financial'] = dict(source_totals=totals, oracle='csv.DictReader + exact Decimal')
        run.check_sources()
        run.validation_token = (run.connection.total_changes, run.scalar('PRAGMA schema_version'))
        return run.report['financial']


    def validate_supporting(run):
        supporting = {}
        frames=read_sources({n:run.root/run.sources[n]['path'] for n in ['sales','sample_submission']})
        v09=submission_analysis(frames['sample_submission'],frames['sales'])
        run.check('supporting:V09_recomputed',all(v09['checks'].values()))
        supporting['sales_template']=v09['metrics']
        # Handoff contains dates only, never the template's example target values.
        supporting['forecast_handoff']=dict(history_source='data/raw/sales.csv',history_columns=['Date','Revenue','COGS'],
            calendar=[r[0] for r in run.connection.execute('SELECT _p_Date FROM sample_submission ORDER BY _p_Date')],
            target_columns=['Revenue','COGS'],template_values_are_labels=False,lag_rolling_scaling=False)
        ncustomers=run.sources['customers']['rows']
        eligible=run.scalar("SELECT COUNT(DISTINCT customer_id) FROM orders WHERE order_status='delivered' AND _p_order_date BETWEEN '2012-07-04' AND '2022-12-31'")
        no_orders=run.scalar('SELECT COUNT(*) FROM customers c WHERE NOT EXISTS(SELECT 1 FROM orders o WHERE o.customer_id=c.customer_id)')
        supporting['rfm_scope']=dict(customers=ncustomers,eligible=eligible,outside=ncustomers-eligible,
            no_order_records=no_orders,orders_but_no_eligible_delivered=ncustomers-eligible-no_orders,
            reference_date='2022-12-31',computed_rfm=False,recency_outside=None)
        # Residual only for consecutive observed product-months. No inserted months.
        stock=run.connection.execute('''WITH x AS (SELECT product_id,_p_stock_on_hand AS stock,
          _p_units_received AS received,_p_units_sold AS sold,CAST(_p_year AS INTEGER)*12+CAST(_p_month AS INTEGER) AS m,
          LAG(_p_stock_on_hand) OVER (PARTITION BY product_id ORDER BY _p_snapshot_date) AS previous_stock,
          LAG(CAST(_p_year AS INTEGER)*12+CAST(_p_month AS INTEGER)) OVER (PARTITION BY product_id ORDER BY _p_snapshot_date) AS previous_m
          FROM inventory) SELECT SUB(SUB(stock,previous_stock),SUB(received,sold)) FROM x WHERE m-previous_m=1''')
        consecutive=zero=0
        for (value,) in stock:
            consecutive+=1;zero+=value is not None and Decimal(value)==0
        supporting['inventory_residual']=dict(eligible_consecutive_pairs=consecutive,zero_residual_pairs=zero,
            physical_stock_verified=False,imputation=False)
        run.report['supporting']=supporting
        run.check_sources()
        return supporting


    def encode(value, kind):
        if value is None or pd.isna(value):return NULL_TOKEN
        if kind=='boolean':return 'True' if value else 'False'
        if kind=='date':return pd.Timestamp(value).date().isoformat()
        text=str(value)
        if text==NULL_TOKEN:raise ValueError('Source string collides with reserved CSV NULL token')
        return text


    def read_processed(path, schema):
        """Streaming typed reader: no NA inference, ID/ZIP conversion or float parsing."""
        with Path(path).open(encoding='utf-8',newline='') as stream:
            reader=csv.reader(stream,strict=True)
            if next(reader,None)!=list(schema):raise ValueError('Processed schema mismatch')
            for row in reader:
                if len(row)!=len(schema):raise ValueError('Processed CSV shape mismatch')
                yield tuple(None if value==NULL_TOKEN else typed_value(value,kind)
                            for value,kind in zip(row,schema.values()))


    def verify_roundtrip(view, path):
        actual=iter(read_processed(path,view.schema));count=0;fingerprint=hashlib.sha256()
        for expected in view.rows():
            observed=next(actual,None)
            if observed is None or observed!=expected:raise ValueError(f'CSV round-trip mismatch at record {count+1}')
            values=[encode(v,k) for v,k in zip(observed,view.schema.values())]
            fingerprint.update((repr(values)+'\n').encode())
            count+=1
        if next(actual,None) is not None:raise ValueError('Extra processed rows')
        return dict(rows=count,schema=view.schema,sha256=digest(Path(path)),canonical_rows_sha256=fingerprint.hexdigest(),
                    exact_row_comparison=True)


    def publish(run, *, output_dir=None):
        """Publish only accepted views; existing identical outputs are verified, never overwritten."""
        if not all(run.report.get(n,{}).get('accepted') for n in ['orders_common','order_items_common']):
            raise ValueError('Views are not accepted; publication blocked')
        if 'financial' not in run.report or 'supporting' not in run.report:
            raise ValueError('Required independent/supporting checks have not run')
        if getattr(run,'validation_token',None) != (run.connection.total_changes,run.scalar('PRAGMA schema_version')):
            raise ValueError('Views changed after validation; run all acceptance checks again')
        run.check_sources()
        output=Path(output_dir) if output_dir else run.root/'data/processed'
        output.mkdir(parents=True, exist_ok=True)
        targets={n:output/(n+'.csv') for n in run.views}

        if any(path.exists() for path in targets.values()):
            if not all(path.is_file() for path in targets.values()):
                raise FileExistsError('Thiếu một trong hai CSV đầu ra. Chọn thư mục kết quả khác để tạo lại.')
            return dict(status='verified_existing', outputs={
                name: verify_roundtrip(run.views[name], path) for name, path in targets.items()
            })
        with tempfile.TemporaryDirectory(prefix='gd2_publish_', dir=output) as directory:
            evidence = {}
            for name, view in run.views.items():
                pending = Path(directory) / targets[name].name
                with pending.open('x', encoding='utf-8', newline='') as stream:
                    writer = csv.writer(stream)
                    writer.writerow(view.schema)
                    writer.writerows([encode(v, k) for v, k in zip(row, view.schema.values())] for row in view.rows())
                    stream.flush()
                    os.fsync(stream.fileno())
                evidence[name] = verify_roundtrip(view, pending)
            run.check_sources()
            created = []
            try:
                for path in targets.values():
                    os.link(Path(directory) / path.name, path)
                    created.append(path)
            except OSError:
                for path in created:
                    path.unlink()
                raise
        return dict(status='published', outputs=evidence)
    return SimpleNamespace(
        csv=csv,
        Decimal=Decimal,
        hashlib=hashlib,
        os=os,
        Path=Path,
        platform=platform,
        tempfile=tempfile,
        pd=pd,
        digest=digest,
        read_sources=read_sources,
        submission_analysis=submission_analysis,
        quote=quote,
        typed_value=typed_value,
        NULL_TOKEN=NULL_TOKEN,
        validate_orders=validate_orders,
        validate_items=validate_items,
        validate_financials=validate_financials,
        validate_supporting=validate_supporting,
        encode=encode,
        read_processed=read_processed,
        verify_roundtrip=verify_roundtrip,
        publish=publish,
    )


@cache
def foundation():
    """Read-only, typed source tables and explicit validation results; no business views."""

    from dataclasses import dataclass
    import csv
    from decimal import Decimal, Inexact, MAX_EMAX, MIN_EMIN, Rounded, localcontext
    import hashlib
    import os
    from pathlib import Path
    from types import MappingProxyType
    from typing import Mapping

    import pandas as pd

    FORMATS = v01().FORMATS
    parse_date = v01().parse_date
    decimal_value = v02().decimal_value
    digest = v02().digest
    require_key = v02().require_key
    require_link = v02().require_link
    null_kind = v06().null_kind
    read_sources = v06().read_sources
    strict_dates = v06().strict_dates

    CONTRACT_VERSION = contracts().CONTRACT_VERSION
    TABLES = contracts().TABLES
    TableSpec = contracts().TableSpec


    class SourceStructureError(ValueError):
        """The file/snapshot/schema cannot safely be interpreted."""


    @dataclass(frozen=True)
    class CheckResult:
        code: str
        status: str  # passed, unsafe, retained, unknown; never coerce unknown to bool.
        table: str
        columns: tuple[str, ...]
        record_indices: tuple[int, ...] = ()  # one-based CSV records, not physical lines
        message: str = ""


    class DataValidationError(ValueError):
        """Unsafe or unavailable data. Evidence and the diagnostic table remain accessible."""

        def __init__(self, checks, table_data=None):
            self.checks = tuple(checks)
            self.table_data = table_data
            super().__init__("; ".join(
                f"{c.table}.{','.join(c.columns)} [{c.status}/{c.code}]: {c.message}"
                for c in self.checks
            ))


    @dataclass(frozen=True)
    class SourceTable:
        contract: TableSpec
        raw: pd.DataFrame
        working: pd.DataFrame
        states: pd.DataFrame
        lineage: pd.DataFrame
        metadata: Mapping
        checks: tuple[CheckResult, ...]

        def require_usable(self, columns=None):
            """Gate the requested columns; unknown is unavailable, not a passed check.

            Frames are independent but mutable: callers must not mutate a working
            frame and then reuse its old checks as validation of the changed frame.
            """
            selected = set(self.working.columns if columns is None else columns)
            missing = selected - set(self.working.columns)
            if missing:
                raise KeyError(f"Unknown columns: {sorted(missing)}")
            blocked = [c for c in self.checks if c.status in {"unsafe", "unknown"}
                       and selected.intersection(c.columns)]
            if blocked:
                raise DataValidationError(blocked, self)
            return self


    def resolve_project_root(root=None, *, start=None):
        """Use an explicit root, or ascend from start/env/cwd; never require reports."""
        def is_root(path):
            return (path / "data/raw").is_dir() and (path / "notebook/ham_dung_chung.py").is_file()

        if root is not None:
            candidate = Path(root).expanduser().resolve()
            if not is_root(candidate):
                raise FileNotFoundError(f"Not a project root (requires data/raw and the shared Python file): {candidate}")
            return candidate
        if start is None and os.environ.get("RETAIL_ANALYTICS_ROOT"):
            return resolve_project_root(os.environ["RETAIL_ANALYTICS_ROOT"])
        origin = Path(start if start is not None else Path.cwd()).expanduser().resolve()
        if origin.is_file():
            origin = origin.parent
        for candidate in (origin, *origin.parents):
            if is_root(candidate):
                return candidate
        raise FileNotFoundError(f"Project root not found above {origin}; pass root explicitly")


    def _indices(mask):
        return tuple(int(i) + 1 for i in mask.index[mask.fillna(False)])


    def _missing_key(frame, columns):
        mask = frame[list(columns)].isna().any(axis=1)
        for column in columns:
            mask |= frame[column].astype("string").str.fullmatch(r"\s*", na=False)
        return mask


    def _key_frame(frame, columns):
        # Tuples are only a membership/uniqueness representation. No rows are removed.
        values = list(frame[list(columns)].itertuples(index=False, name=None))
        return pd.DataFrame({"_key": values}, index=frame.index)


    def _key_check(frame, columns, table):
        missing = _missing_key(frame, columns)
        if missing.any():
            return CheckResult("missing_key", "unsafe", table, columns, _indices(missing),
                               "NULL/empty/whitespace key; no join is permitted")
        view = frame if len(columns) == 1 else _key_frame(frame, columns)
        key = columns[0] if len(columns) == 1 else "_key"
        try:
            require_key(view, key, table)
        except ValueError as exc:
            return CheckResult("duplicate_key", "unsafe", table, columns,
                               _indices(frame.duplicated(list(columns), keep=False)), str(exc))
        return CheckResult("key", "passed", table, columns, message="Unique, non-missing key")


    def _parse_column(raw, spec):
        kinds = raw.map(null_kind)
        states = pd.Series("valid", index=raw.index, dtype="string")
        states.loc[kinds.eq("missing_or_empty")] = "empty"
        states.loc[kinds.eq("text_null_token")] = "null_token"
        whitespace = raw.str.fullmatch(r"\s+", na=False)
        states.loc[whitespace] = "whitespace"
        present = states.eq("valid")
        text = raw.where(present, pd.NA).astype("string")
        if spec.kind == "string":
            # Preserve whitespace-only text for diagnosis; it is not asserted to be NULL.
            values = raw.where(kinds.eq("non_null"), pd.NA).astype("string")
        elif spec.kind == "date":
            if FORMATS.get(spec.name) == spec.date_format:
                values, _ = parse_date(text, spec.name)
            elif spec.date_format == "%Y-%m-%d":
                values, _ = strict_dates(text)
            else:
                raise SourceStructureError(f"Unsupported date contract: {spec.name}/{spec.date_format}")
            states.loc[present & values.isna()] = "invalid_date"
        else:
            parsed = []
            state_values = states.tolist()
            for position, value in enumerate(text.array):
                if state_values[position] != "valid":
                    parsed.append(pd.NA)
                    continue
                try:
                    number = decimal_value(value)  # exact construction from the source lexeme
                except ValueError:
                    state_values[position] = "invalid_numeric"
                    parsed.append(pd.NA)
                    continue
                if spec.kind == "integer":
                    if number != number.to_integral_value():
                        state_values[position] = "non_integer"
                        parsed.append(pd.NA)
                        continue
                    if not -(2**63) <= number <= 2**63 - 1:
                        state_values[position] = "integer_out_of_range"
                        parsed.append(pd.NA)
                        continue
                    number = int(number)
                parsed.append(number)
            values = pd.Series(parsed, index=raw.index,
                               dtype="Int64" if spec.kind == "integer" else object)
            states = pd.Series(state_values, index=raw.index, dtype="string")
        return values, states


    def read_source_table(name, *, root=None, path=None, strict=True):
        """Read a contracted CSV without writing; strict=False returns diagnostic evidence.

        raw contains decoded CSV field values (not quote syntax); the source hash
        identifies the exact bytes. working and states have the same row order.
        Foreign keys require validate_foreign_keys() with the referenced tables.
        """
        if name not in TABLES:
            raise KeyError(f"No input contract for table {name!r}")
        contract = TABLES[name]
        project = resolve_project_root(root)
        source = Path(path) if path is not None else project / "data/raw" / f"{name}.csv"
        source = source if source.is_absolute() else project / source
        source = source.resolve()
        try:
            relative = source.relative_to(project).as_posix()
        except ValueError as exc:
            raise SourceStructureError("Source must be inside the explicit project root") from exc
        before = digest(source)
        try:
            # V06 reuses profile_table.read_table for strict CSV shape/ID validation,
            # then rereads exact strings with keep_default_na=False. Inferred floats
            # are diagnostic only and never enter our working monetary values.
            raw = read_sources({name: source})[name]
        except (ValueError, pd.errors.ParserError, UnicodeError) as exc:
            raise SourceStructureError(f"{relative}: {exc}") from exc
        if digest(source) != before:
            raise SourceStructureError(f"Source changed while reading: {relative}")
        actual = tuple(raw.columns)
        expected = contract.required_columns
        if actual != expected:
            missing = sorted(set(expected) - set(actual))
            extra = sorted(set(actual) - set(expected))
            raise SourceStructureError(
                f"{relative}: schema drift; missing={missing}, extra={extra}, "
                f"column_order_matches={actual == expected}")
        working = raw.copy(deep=True)
        states = pd.DataFrame(index=raw.index)
        checks = []
        for column in contract.columns:
            working[column.name], state = _parse_column(raw[column.name], column)
            states[column.name] = state
            for kind in state.unique():
                mask = state.eq(kind)
                if kind == "valid":
                    continue
                status = ("retained" if column.null_policy == "allowed" and kind in {"empty", "null_token"}
                          else "unknown" if kind in {"empty", "null_token", "whitespace"} else "unsafe")
                checks.append(CheckResult(str(kind), status, name, (column.name,), _indices(mask),
                                          f"{int(mask.sum())} records; source values retained"))
        for columns in contract.keys:
            checks.append(_key_check(working, columns, name))
        # Even a repeatable child has non-missing mandatory relationship keys.
        for relation in contract.foreign_keys:
            if not relation.nullable:
                mask = _missing_key(working, relation.columns)
                if mask.any():
                    checks.append(CheckResult("missing_foreign_key", "unsafe", name,
                                              relation.columns, _indices(mask), "Mandatory relationship key missing"))
        for columns in (*contract.repeatable_pairs, *contract.snapshot_unique_keys):
            repeated = working.duplicated(list(columns), keep=False)
            if repeated.any():
                checks.append(CheckResult("repeated_source_key", "retained", name, columns,
                                          _indices(repeated), "Keep every source record; aggregate before joining"))
        if name == "inventory":
            available = working[["snapshot_date", "year", "month"]].notna().all(axis=1)
            mismatch = available & (working.year.ne(working.snapshot_date.dt.year)
                                    | working.month.ne(working.snapshot_date.dt.month))
            if mismatch.any():
                checks.append(CheckResult("snapshot_period_mismatch", "unsafe", name,
                                          ("snapshot_date", "year", "month"), _indices(mismatch),
                                          "Cannot interpret product-month key; do not repair source fields"))
        indices = range(1, len(raw) + 1)
        lineage = pd.DataFrame({
            "source_record_index": pd.Series(indices, dtype="Int64"),
            "source_row_id": pd.Series([
                hashlib.sha256(f"{relative}\0{before}\0{i}".encode("utf-8")).hexdigest()
                for i in indices
            ], dtype="string"),
        })
        metadata = MappingProxyType(dict(
            table=name, source_path=relative, source_sha256=before, row_count=len(raw),
            columns=actual, encoding="utf-8-sig", separator=",",
            contract_version=CONTRACT_VERSION, grain=contract.grain,
            source_record_index_base=1,
        ))
        if digest(source) != before:
            raise SourceStructureError(f"Source changed while preparing working data: {relative}")
        result = SourceTable(contract, raw, working, states, lineage, metadata, tuple(checks))
        if strict:
            result.require_usable()
        return result


    def validate_foreign_keys(tables: Mapping[str, SourceTable], *, strict=True):
        """Check verified membership, not child coverage; missing parents are unknown.

        Composite references to item pairs use a key set only for membership. They
        never deduplicate the source records or claim an individual item-row match.
        """
        checks = []
        for name, child in tables.items():
            if name != child.contract.name:
                raise ValueError(f"Mapping key {name!r} does not match {child.contract.name!r}")
            for relation in child.contract.foreign_keys:
                parent = tables.get(relation.parent_table)
                label = f"{name} -> {relation.parent_table}"
                if parent is None:
                    checks.append(CheckResult("parent_not_loaded", "unknown", name, relation.columns,
                                              message=label + ": cannot evaluate without parent table"))
                    continue
                try:
                    child.require_usable(relation.columns)
                    parent.require_usable(relation.parent_columns)
                except DataValidationError as exc:
                    status = "unsafe" if any(c.status == "unsafe" for c in exc.checks) else "unknown"
                    checks.append(CheckResult("relation_unavailable", status, name, relation.columns,
                                              message=label + ": " + str(exc)))
                    continue
                cframe = _key_frame(child.working, relation.columns)
                pframe = _key_frame(parent.working, relation.parent_columns)
                if relation.parent_unique:
                    parent_check = _key_check(parent.working, relation.parent_columns, relation.parent_table)
                    if parent_check.status != "passed":
                        checks.append(CheckResult("ambiguous_parent", "unsafe", name, relation.columns,
                                                  message=label + ": " + parent_check.message))
                        continue
                missing = _missing_key(child.working, relation.columns)
                active = ~missing if relation.nullable else pd.Series(True, index=cframe.index)
                # Empty/NULL optional keys are excluded; whitespace-only keys have
                # already been classified unknown by require_usable above.
                try:
                    require_link(cframe.loc[active], pframe, "_key", label)
                except ValueError as exc:
                    orphan = active & ~cframe._key.isin(pframe._key)
                    checks.append(CheckResult("orphan_foreign_key", "unsafe", name, relation.columns,
                                              _indices(orphan), str(exc)))
                    continue
                checks.append(CheckResult("foreign_key", "passed", name, relation.columns, message=label))
        if strict:
            blocked = [c for c in checks if c.status in {"unsafe", "unknown"}]
            if blocked:
                raise DataValidationError(blocked)
        return tuple(checks)


    def _exact_numbers(values):
        result = []
        for value in values:
            if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
                raise TypeError("Exact arithmetic requires finite Decimal/int; no float, NULL or string")
            result.append(decimal_value(value))
        return result


    def _arithmetic(values, *, product):
        numbers = _exact_numbers(values)
        if not numbers:
            return Decimal(1 if product else 0)
        if product:
            precision = sum(len(v.as_tuple().digits) for v in numbers) + 1
        else:
            low = min(v.as_tuple().exponent for v in numbers)
            high = max(v.adjusted() + 1 for v in numbers)
            precision = max(1, high - low + len(str(len(numbers))) + 1)
        with localcontext() as context:
            context.prec = precision
            context.Emax, context.Emin = MAX_EMAX, MIN_EMIN
            context.clamp = 0
            context.traps[Inexact] = context.traps[Rounded] = True
            result = Decimal(1 if product else 0)
            for value in numbers:
                result = result * value if product else result + value
            return result


    def exact_sum(values):
        """Exact scalar sum independent of caller precision; refuses missing/float values."""
        return _arithmetic(values, product=False)


    def exact_product(*values):
        """Exact scalar product; no business aggregation or cent quantization."""
        return _arithmetic(values, product=True)


    def iter_source_chunks(name, *, root=None, chunk_size=25000):
        """Stream lexemes and parsed copies with global record IDs, without writing.

        Exhaust the generator to verify the final source hash. Global uniqueness/FK
        checks are the caller's responsibility; per-chunk checks are not sufficient.
        """
        if name not in TABLES:
            raise KeyError(name)
        if chunk_size < 1:
            raise ValueError("chunk_size must be positive")
        project = resolve_project_root(root)
        path = project / "data/raw" / f"{name}.csv"
        relative = path.relative_to(project).as_posix()
        source_hash = digest(path)
        spec = TABLES[name]

        def prepare(records, start):
            raw = pd.DataFrame(records, columns=spec.required_columns, dtype="string",
                               index=pd.RangeIndex(start, start + len(records)))
            working = raw.copy(deep=True)
            states = pd.DataFrame(index=raw.index)
            checks = []
            for col in spec.columns:
                working[col.name], states[col.name] = _parse_column(raw[col.name], col)
                for state in states[col.name].unique():
                    if state == "valid":
                        continue
                    mask = states[col.name].eq(state)
                    status = ("retained" if col.null_policy == "allowed" and state in {"empty", "null_token"}
                              else "unknown" if state in {"empty", "null_token", "whitespace"} else "unsafe")
                    checks.append(CheckResult(str(state), status, name, (col.name,), _indices(mask),
                                              f"{int(mask.sum())} records; source retained"))
            required = {key for group in spec.keys for key in group}
            required.update(key for fk in spec.foreign_keys if not fk.nullable for key in fk.columns)
            for key in sorted(required):
                mask = _missing_key(working, (key,))
                if mask.any():
                    checks.append(CheckResult("missing_key", "unsafe", name, (key,), _indices(mask), "Key unavailable"))
            ids = [hashlib.sha256(f"{relative}\0{source_hash}\0{i + 1}".encode()).hexdigest()
                   for i in raw.index]
            lineage = pd.DataFrame({"source_record_index": [int(i) + 1 for i in raw.index],
                                    "source_row_id": ids}, index=raw.index)
            metadata = MappingProxyType(dict(table=name, source_path=relative, source_sha256=source_hash,
                                             contract_version=CONTRACT_VERSION, chunk_start=start + 1))
            return SourceTable(spec, raw, working, states, lineage, metadata, tuple(checks))

        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.reader(stream, strict=True)
            try:
                header = next(reader, None)
                if header != list(spec.required_columns):
                    raise SourceStructureError(f"{relative}: schema/header mismatch")
                batch, start = [], 0
                for row in reader:
                    if len(row) != len(header):
                        raise SourceStructureError(f"{relative}: CSV record has {len(row)} fields, expected {len(header)}")
                    batch.append(row)
                    if len(batch) == chunk_size:
                        yield prepare(batch, start)
                        start += len(batch)
                        batch = []
                if batch or start == 0:
                    yield prepare(batch, start)
            except csv.Error as exc:
                raise SourceStructureError(f"{relative}: {exc}") from exc
        if digest(path) != source_hash:
            raise SourceStructureError(f"{relative}: source changed during streaming")
    return SimpleNamespace(
        dataclass=dataclass,
        csv=csv,
        Decimal=Decimal,
        Inexact=Inexact,
        MAX_EMAX=MAX_EMAX,
        MIN_EMIN=MIN_EMIN,
        Rounded=Rounded,
        localcontext=localcontext,
        hashlib=hashlib,
        os=os,
        Path=Path,
        MappingProxyType=MappingProxyType,
        Mapping=Mapping,
        pd=pd,
        FORMATS=FORMATS,
        parse_date=parse_date,
        decimal_value=decimal_value,
        digest=digest,
        require_key=require_key,
        require_link=require_link,
        null_kind=null_kind,
        read_sources=read_sources,
        strict_dates=strict_dates,
        CONTRACT_VERSION=CONTRACT_VERSION,
        TABLES=TABLES,
        TableSpec=TableSpec,
        SourceStructureError=SourceStructureError,
        CheckResult=CheckResult,
        DataValidationError=DataValidationError,
        SourceTable=SourceTable,
        resolve_project_root=resolve_project_root,
        read_source_table=read_source_table,
        validate_foreign_keys=validate_foreign_keys,
        exact_sum=exact_sum,
        exact_product=exact_product,
        iter_source_chunks=iter_source_chunks,
    )


@cache
def segmentation_defaults():
    """Customer segmentation: explicit snapshot scope, exact-money RFM and reproducible experiments."""
    from pathlib import Path
    from decimal import Decimal
    import hashlib,platform,re,time
    import numpy as np
    import pandas as pd
    import sklearn
    from sklearn.preprocessing import StandardScaler
    from sklearn.cluster import KMeans,AgglomerativeClustering
    from sklearn.metrics import silhouette_score,davies_bouldin_score,adjusted_rand_score
    from threadpoolctl import threadpool_limits
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    exact_sum = foundation().exact_sum
    resolve_project_root = foundation().resolve_project_root

    FEATURES=['Recency','Frequency','Monetary']
    CUTOFF=pd.Timestamp('2022-12-31')


    def sha(path):
        return file_sha(path)


    def require(ok,message):
        if not bool(ok):raise ValueError(message)
    return SimpleNamespace(
        Path=Path,
        Decimal=Decimal,
        hashlib=hashlib,
        platform=platform,
        re=re,
        time=time,
        np=np,
        pd=pd,
        sklearn=sklearn,
        StandardScaler=StandardScaler,
        KMeans=KMeans,
        AgglomerativeClustering=AgglomerativeClustering,
        silhouette_score=silhouette_score,
        davies_bouldin_score=davies_bouldin_score,
        adjusted_rand_score=adjusted_rand_score,
        threadpool_limits=threadpool_limits,
        matplotlib=matplotlib,
        plt=plt,
        exact_sum=exact_sum,
        resolve_project_root=resolve_project_root,
        FEATURES=FEATURES,
        CUTOFF=CUTOFF,
        sha=sha,
        require=require,
    )


@cache
def segmentation_experiments():
    """Các bước experiments của bài toán phân cụm."""
    Decimal = segmentation_defaults().Decimal
    Path = segmentation_defaults().Path
    FEATURES = segmentation_defaults().FEATURES
    CUTOFF = segmentation_defaults().CUTOFF
    sha = segmentation_defaults().sha
    require = segmentation_defaults().require
    np = segmentation_defaults().np
    pd = segmentation_defaults().pd
    plt = segmentation_defaults().plt
    re = segmentation_defaults().re
    time = segmentation_defaults().time
    platform = segmentation_defaults().platform
    sklearn = segmentation_defaults().sklearn
    exact_sum = segmentation_defaults().exact_sum
    resolve_project_root = segmentation_defaults().resolve_project_root
    StandardScaler = segmentation_defaults().StandardScaler
    KMeans = segmentation_defaults().KMeans
    AgglomerativeClustering = segmentation_defaults().AgglomerativeClustering
    silhouette_score = segmentation_defaults().silhouette_score
    davies_bouldin_score = segmentation_defaults().davies_bouldin_score
    adjusted_rand_score = segmentation_defaults().adjusted_rand_score
    threadpool_limits = segmentation_defaults().threadpool_limits
    rfm = rfm_features().rfm
    feature_matrix = segmentation_transform().feature_matrix

    def scores(x,labels):
        count=len(np.unique(labels))
        if count<2 or count>=len(labels):return {'silhouette':np.nan,'davies_bouldin':np.nan}
        return dict(silhouette=float(silhouette_score(x,labels)),davies_bouldin=float(davies_bouldin_score(x,labels)))


    class ExperimentSteps:
        def experiments(self):
            f=self.features;rng=np.random.default_rng(42);self.idx=np.sort(rng.choice(len(f),min(5000,len(f)),replace=False));self.save('silhouette_sample',f.iloc[self.idx][['customer_id']])
            rows=[];self.models={};self.matrices={};self.scalers={}
            with threadpool_limits(limits=1):
                for variant in ['TN1','TN2']:
                    x,scaler=feature_matrix(f,variant);self.matrices[variant]=x;self.scalers[variant]=scaler
                    for k in range(2,9):
                        start=time.monotonic();model=KMeans(n_clusters=k,init='k-means++',n_init=10,random_state=42,max_iter=300).fit(x)
                        labels=model.labels_;counts=np.bincount(labels);samplelabels=labels[self.idx]
                        silhouette=scores(x[self.idx],samplelabels)['silhouette']
                        rows.append(dict(variant=variant,k=k,silhouette_sample=silhouette,davies_bouldin_full=float(davies_bouldin_score(x,labels)),inertia=float(model.inertia_),min_cluster_share=float(counts.min()/len(f)),max_cluster_share=float(counts.max()/len(f)),seconds=time.monotonic()-start))
                        self.models[(variant,k)]=model
                        print(f'{variant}, k={k}: silhouette={silhouette:.4f}; min_share={counts.min()/len(f):.2%}',flush=True)
            self.grid=pd.DataFrame(rows)
            # Explicit exploratory shortlisting; no metric is business approval.
            eligible=self.grid.loc[self.grid.min_cluster_share.ge(.01)].copy();require(len(eligible)>0,'No candidate with all clusters >=1%')
            eligible['rank_sum']=eligible.silhouette_sample.rank(ascending=False)+eligible.davies_bouldin_full.rank()
            self.shortlist=eligible.sort_values(['rank_sum','k','variant']).head(3)
            self.save('experiment_grid',self.grid);self.save('shortlist',self.shortlist)
            profile_rows=[]
            for _,row in self.grid.iterrows():
                labels=self.models[(row.variant,int(row.k))].labels_
                for cl,h in f.assign(cluster=labels).groupby('cluster'):
                    profile_rows.append(dict(variant=row.variant,k=int(row.k),cluster=int(cl),customers=len(h),Recency_median=float(h.Recency.median()),Frequency_median=float(h.Frequency.median()),Monetary_median=float(h.Monetary.astype(float).median())))
            self.save('candidate_profiles',pd.DataFrame(profile_rows))
            fig,axes=plt.subplots(1,3,figsize=(13,3.5))
            for variant,g in self.grid.groupby('variant'):
                for ax,col in zip(axes,['silhouette_sample','davies_bouldin_full','inertia']):ax.plot(g.k,g[col],marker='o',label=variant);ax.set(title=col,xlabel='k')
            axes[0].legend();fig.tight_layout();plt.close(fig)
            return self.grid

        def stability(self):
            rows=[]
            with threadpool_limits(limits=1):
                for _,row in self.shortlist.iterrows():
                    key=(row.variant,int(row.k));x=self.matrices[key[0]];base=self.models[key].labels_
                    for seed in [7,21,84]:
                        labels=KMeans(n_clusters=key[1],n_init=10,random_state=seed,max_iter=300).fit_predict(x)
                        rows.append(dict(variant=key[0],k=key[1],seed=seed,ari=float(adjusted_rand_score(base,labels))))
            self.stability_table=pd.DataFrame(rows);self.save('seed_stability',self.stability_table)
            meanari=self.stability_table.groupby(['variant','k']).ari.mean()
            stable=[(r.variant,int(r.k)) for r in self.shortlist.itertuples() if meanari.loc[(r.variant,int(r.k))]>=.90]
            require(len(stable)>0,'No shortlisted model passes exploratory mean ARI >=0.90; inspect instead of forcing a choice')
            self.key=stable[0];self.model=self.models[self.key];self.x=self.matrices[self.key[0]];self.scaler=self.scalers[self.key[0]]
            return self.stability_table

        def hierarchy(self):
            # Controlled sample-fit algorithm comparison, independent from full-data fit scores.
            rng=np.random.default_rng(24);idx=np.sort(rng.choice(len(self.features),min(3500,len(self.features)),replace=False));xs=self.x[idx];rows=[];labels={}
            self.save('hierarchy_sample',self.features.iloc[idx][['customer_id']])
            with threadpool_limits(limits=1):
                for k in sorted({2,3,4,self.key[1]}):
                    km=KMeans(n_clusters=k,n_init=10,random_state=42).fit_predict(xs);hl=AgglomerativeClustering(n_clusters=k,linkage='ward').fit_predict(xs)
                    for name,y in [('KMeans_sample',km),('Hierarchical_Ward_sample',hl)]:
                        rows.append(dict(algorithm=name,k=k,fit_customers=len(xs),**scores(xs,y)))
                    labels[k]=(km,hl)
            self.hierarchy_table=pd.DataFrame(rows);self.save('hierarchical_comparison',self.hierarchy_table)
            self.save('hierarchy_agreement', pd.DataFrame([{'k': k, 'ARI hai thuật toán': float(adjusted_rand_score(*v))} for k, v in labels.items()]))
            return self.hierarchy_table
    return SimpleNamespace(
        Decimal=Decimal,
        Path=Path,
        FEATURES=FEATURES,
        CUTOFF=CUTOFF,
        sha=sha,
        require=require,
        np=np,
        pd=pd,
        plt=plt,
        re=re,
        time=time,
        platform=platform,
        sklearn=sklearn,
        exact_sum=exact_sum,
        resolve_project_root=resolve_project_root,
        StandardScaler=StandardScaler,
        KMeans=KMeans,
        AgglomerativeClustering=AgglomerativeClustering,
        silhouette_score=silhouette_score,
        davies_bouldin_score=davies_bouldin_score,
        adjusted_rand_score=adjusted_rand_score,
        threadpool_limits=threadpool_limits,
        rfm=rfm,
        feature_matrix=feature_matrix,
        scores=scores,
        ExperimentSteps=ExperimentSteps,
    )


@cache
def segmentation_profiling():
    """Các bước profiling của bài toán phân cụm."""
    Decimal = segmentation_defaults().Decimal
    Path = segmentation_defaults().Path
    FEATURES = segmentation_defaults().FEATURES
    CUTOFF = segmentation_defaults().CUTOFF
    sha = segmentation_defaults().sha
    require = segmentation_defaults().require
    np = segmentation_defaults().np
    pd = segmentation_defaults().pd
    plt = segmentation_defaults().plt
    re = segmentation_defaults().re
    time = segmentation_defaults().time
    platform = segmentation_defaults().platform
    sklearn = segmentation_defaults().sklearn
    exact_sum = segmentation_defaults().exact_sum
    resolve_project_root = segmentation_defaults().resolve_project_root
    StandardScaler = segmentation_defaults().StandardScaler
    KMeans = segmentation_defaults().KMeans
    AgglomerativeClustering = segmentation_defaults().AgglomerativeClustering
    silhouette_score = segmentation_defaults().silhouette_score
    davies_bouldin_score = segmentation_defaults().davies_bouldin_score
    adjusted_rand_score = segmentation_defaults().adjusted_rand_score
    threadpool_limits = segmentation_defaults().threadpool_limits
    rfm = rfm_features().rfm
    feature_matrix = segmentation_transform().feature_matrix

    class ProfileSteps:
        def profile(self):
            f=self.features.copy();f['center_id']=self.model.labels_
            # Display labels sorted by original Monetary mean; prediction still uses saved center mapping.
            order=f.assign(m=f.Monetary.astype(float)).groupby('center_id').m.mean().sort_values().index
            self.mapping={int(center):int(cl) for cl,center in enumerate(order)};f['cluster']=f.center_id.map(self.mapping)
            self.assignments=f.merge(self.behaviors,on='customer_id',how='left',validate='one_to_one')
            self.save('customer_segments',self.assignments,data=True)
            members=self.scope.merge(f[['customer_id','cluster']],on='customer_id',how='left',validate='one_to_one');members['cluster']=members.cluster.astype('Int64');self.save('all_customer_assignments',members,data=True)
            x=self.assignments.copy();x['Monetary']=x.Monetary.astype(float)
            self.profiles=x.groupby('cluster').agg(customers=('customer_id','size'),Recency_median=('Recency','median'),Frequency_median=('Frequency','median'),Monetary_median=('Monetary','median'),Monetary_total=('Monetary','sum'),cancelled_share_mean=('cancelled_share','mean'),returned_status_share_mean=('returned_share','mean'),return_detail_share_mean=('return_detail_share','mean'),missing_shipment_share_mean=('delivered_missing_shipment_share','mean'),distinct_products_median=('distinct_products','median'))
            self.profiles['customer_share']=self.profiles.customers/len(x);self.profiles['Monetary_share']=self.profiles.Monetary_total/x.Monetary.sum()
            self.save('cluster_profiles',self.profiles.reset_index())
            fig,ax=plt.subplots(figsize=(8,4));sample=x.iloc[self.idx]
            for cl,g in sample.groupby('cluster'):ax.scatter(g.Recency,np.log1p(g.Monetary),s=6,alpha=.45,label=f'Group {cl}')
            ax.set(xlabel='Recency (days)',ylabel='log1p(Monetary)',title='Primary clusters — fixed sample; original RFM, log display only');ax.legend();fig.tight_layout();plt.close(fig)
            return self.profiles
    return SimpleNamespace(
        Decimal=Decimal,
        Path=Path,
        FEATURES=FEATURES,
        CUTOFF=CUTOFF,
        sha=sha,
        require=require,
        np=np,
        pd=pd,
        plt=plt,
        re=re,
        time=time,
        platform=platform,
        sklearn=sklearn,
        exact_sum=exact_sum,
        resolve_project_root=resolve_project_root,
        StandardScaler=StandardScaler,
        KMeans=KMeans,
        AgglomerativeClustering=AgglomerativeClustering,
        silhouette_score=silhouette_score,
        davies_bouldin_score=davies_bouldin_score,
        adjusted_rand_score=adjusted_rand_score,
        threadpool_limits=threadpool_limits,
        rfm=rfm,
        feature_matrix=feature_matrix,
        ProfileSteps=ProfileSteps,
    )


@cache
def rfm_features():
    """RFM chính xác và hành vi bổ trợ; không chứa mô hình."""
    Decimal = segmentation_defaults().Decimal
    Path = segmentation_defaults().Path
    FEATURES = segmentation_defaults().FEATURES
    CUTOFF = segmentation_defaults().CUTOFF
    sha = segmentation_defaults().sha
    require = segmentation_defaults().require
    np = segmentation_defaults().np
    pd = segmentation_defaults().pd
    plt = segmentation_defaults().plt
    re = segmentation_defaults().re
    time = segmentation_defaults().time
    platform = segmentation_defaults().platform
    sklearn = segmentation_defaults().sklearn
    exact_sum = segmentation_defaults().exact_sum
    resolve_project_root = segmentation_defaults().resolve_project_root
    StandardScaler = segmentation_defaults().StandardScaler
    KMeans = segmentation_defaults().KMeans
    AgglomerativeClustering = segmentation_defaults().AgglomerativeClustering
    silhouette_score = segmentation_defaults().silhouette_score
    davies_bouldin_score = segmentation_defaults().davies_bouldin_score
    adjusted_rand_score = segmentation_defaults().adjusted_rand_score
    threadpool_limits = segmentation_defaults().threadpool_limits

    def rfm(orders,cutoff=CUTOFF):
        """Input is already the explicitly selected order population; Decimal retained in exported table."""
        require(orders.order_id.is_unique,'order_id must be unique before RFM')
        require(orders[['order_id','customer_id','order_date','net_amount']].notna().all().all(),'RFM inputs contain missing values')
        require(orders.order_date.le(cutoff).all(),'Orders after cutoff are not eligible')
        require(orders.net_amount.map(lambda x:isinstance(x,Decimal) and x.is_finite() and x>=0).all(),'Net must be finite nonnegative Decimal')
        groups=orders.groupby('customer_id',sort=True)
        result=groups.agg(last_order_date=('order_date','max'),first_order_date=('order_date','min'),Frequency=('order_id','nunique'))
        result['Recency']=(cutoff-result.last_order_date).dt.days
        result['Monetary']=groups.net_amount.agg(lambda x:exact_sum(x.tolist()))
        result['active_days']=groups.order_date.nunique()
        result['observed_span_days']=(result.last_order_date-result.first_order_date).dt.days
        result['mean_gap_days']=result.observed_span_days/(result.Frequency-1).replace(0,np.nan)
        require(result.Frequency.sum()==len(orders),'Frequency does not reconcile')
        require(exact_sum(result.Monetary.tolist())==exact_sum(orders.net_amount.tolist()),'Monetary does not reconcile exactly')
        return result.reset_index()


    class FeatureSteps:
        def prepare(self):
            path = self.root / 'data/processed/orders_common.csv'
            require(path.is_file(), 'Cần chạy GD2 để có orders_common.csv')
            use=['order_id','customer_id','order_date_parsed','order_status','net_amount','gross_amount','discount_amount_total','quantity_total','delivered_missing_shipment_flag','order_before_signup_flag']
            d=pd.read_csv(path,dtype=str,keep_default_na=False,usecols=use).rename(columns={'order_date_parsed':'order_date'})
            d['order_date']=pd.to_datetime(d.order_date,format='%Y-%m-%d',errors='raise')
            for col in ['net_amount','gross_amount','discount_amount_total']:d[col]=d[col].map(Decimal)
            d['quantity_total']=pd.to_numeric(d.quantity_total,errors='raise')
            require(d.order_id.is_unique,'Common orders duplicate keys')
            require(d.order_id.isin(self.sources['orders'].order_id).all() and len(d)==len(self.sources['orders']),'Common/source population mismatch')
            self.orders=d;self.selected=d.loc[d.order_status.eq('delivered')&d.order_date.le(CUTOFF)].copy();self.features=rfm(self.selected)
            customers=self.sources['customers'][['customer_id']].copy()
            customers['has_orders']=customers.customer_id.isin(d.customer_id);customers['eligible']=customers.customer_id.isin(self.features.customer_id)
            customers['scope_reason']=np.select([customers.eligible,~customers.has_orders],['eligible_delivered','no_order_records'],default='orders_but_no_eligible_delivered')
            self.scope=customers;self.save('customer_scope',customers,data=True);self.save('rfm_exact',self.features,data=True)
            self.manifest['scope_counts']=customers.scope_reason.value_counts().to_dict();self.manifest['eligible_orders']=len(self.selected);self.manifest['exact_net_total']=str(exact_sum(self.features.Monetary.tolist()))
            self.save('scope_summary',customers.scope_reason.value_counts().rename_axis('reason').reset_index(name='customers'))
            return self.features.head(10)

        def behavior(self):
            d=self.orders.loc[self.orders.order_date.le(CUTOFF)];g=d.groupby('customer_id')
            b=g.agg(total_orders=('order_id','nunique'),last_any_order=('order_date','max'))
            b['recency_any_order']=(CUTOFF-b.last_any_order).dt.days
            counts=pd.crosstab(d.customer_id,d.order_status)
            for status in ['created','paid','shipped','delivered','cancelled','returned']:
                b[status+'_orders']=counts.get(status,pd.Series(0,index=counts.index));b[status+'_share']=b[status+'_orders']/b.total_orders
            return_ids=set(self.sources['returns'].order_id)
            b['orders_with_return_detail']=d.assign(has_return=d.order_id.isin(return_ids)).groupby('customer_id').has_return.sum()
            b['return_detail_share']=b.orders_with_return_detail/b.total_orders
            missing=self.selected.order_id.isin(self.shipments.order_id)==False
            a=self.selected.assign(missing_shipment=missing).groupby('customer_id').agg(missing_shipment_orders=('missing_shipment','sum'),units=('quantity_total','sum'))
            b=b.join(a)
            f=self.features.set_index('customer_id');b['delivered_missing_shipment_share']=b.missing_shipment_orders/f.Frequency
            b['average_order_value']=f.Monetary.astype(float)/f.Frequency;b['units_per_delivered_order']=b.units/f.Frequency
            # product breadth is counted from source rows; repeated pairs are retained, nunique is intentional here.
            items=pd.read_csv(self.root/'data/raw/order_items.csv',dtype=str,keep_default_na=False,usecols=['order_id','product_id'])
            ip=items.merge(self.selected[['order_id','customer_id']],on='order_id',how='inner',validate='many_to_one')
            b['distinct_products']=ip.groupby('customer_id').product_id.nunique()
            self.behaviors=b.reset_index();self.save('customer_behavior',self.behaviors,data=True)
            self.quality={'eligible_customers':len(f),'unique_customers':int(f.index.nunique()),'frequency_sum':int(f.Frequency.sum()),'one_order_customers':int(f.Frequency.eq(1).sum()),'one_order_share':float(f.Frequency.eq(1).mean()),'null_mean_gap_expected':int(f.mean_gap_days.isna().sum()),'RFM_nulls':int(f[FEATURES].isna().sum().sum()),'P99':{k:float(v) for k,v in f[FEATURES].astype(float).quantile(.99).items()},'max':{k:float(v) for k,v in f[FEATURES].astype(float).max().items()},'skew':{k:float(v) for k,v in f[FEATURES].astype(float).skew().items()},'behavior_usage':'Profiling only; not input to primary RFM clustering. Shares describe observed snapshot status.'}
            fig,axes=plt.subplots(1,3,figsize=(12,3.5))
            for ax,col in zip(axes,FEATURES):ax.hist(f[col].astype(float),bins=45,color='#247b92');ax.set(title=col,xlabel='Source scale',ylabel='Customers')
            fig.tight_layout();plt.close(fig)
            return self.behaviors.head(10)
    return SimpleNamespace(
        Decimal=Decimal,
        Path=Path,
        FEATURES=FEATURES,
        CUTOFF=CUTOFF,
        sha=sha,
        require=require,
        np=np,
        pd=pd,
        plt=plt,
        re=re,
        time=time,
        platform=platform,
        sklearn=sklearn,
        exact_sum=exact_sum,
        resolve_project_root=resolve_project_root,
        StandardScaler=StandardScaler,
        KMeans=KMeans,
        AgglomerativeClustering=AgglomerativeClustering,
        silhouette_score=silhouette_score,
        davies_bouldin_score=davies_bouldin_score,
        adjusted_rand_score=adjusted_rand_score,
        threadpool_limits=threadpool_limits,
        rfm=rfm,
        FeatureSteps=FeatureSteps,
    )


@cache
def segmentation_scope():
    """Các bước scope_checks của bài toán phân cụm."""
    Decimal = segmentation_defaults().Decimal
    Path = segmentation_defaults().Path
    FEATURES = segmentation_defaults().FEATURES
    CUTOFF = segmentation_defaults().CUTOFF
    sha = segmentation_defaults().sha
    require = segmentation_defaults().require
    np = segmentation_defaults().np
    pd = segmentation_defaults().pd
    plt = segmentation_defaults().plt
    re = segmentation_defaults().re
    time = segmentation_defaults().time
    platform = segmentation_defaults().platform
    sklearn = segmentation_defaults().sklearn
    exact_sum = segmentation_defaults().exact_sum
    resolve_project_root = segmentation_defaults().resolve_project_root
    StandardScaler = segmentation_defaults().StandardScaler
    KMeans = segmentation_defaults().KMeans
    AgglomerativeClustering = segmentation_defaults().AgglomerativeClustering
    silhouette_score = segmentation_defaults().silhouette_score
    davies_bouldin_score = segmentation_defaults().davies_bouldin_score
    adjusted_rand_score = segmentation_defaults().adjusted_rand_score
    threadpool_limits = segmentation_defaults().threadpool_limits
    rfm = rfm_features().rfm
    feature_matrix = segmentation_transform().feature_matrix

    class ScopeSteps:
        def audit(self):
            raw=self.root/'data/raw'
            self.sources={n:pd.read_csv(raw/(n+'.csv'),dtype=str,keep_default_na=False) for n in ['orders','customers','payments','shipments','returns','reviews']}
            o=self.sources['orders'];require(o.order_id.is_unique,'Duplicate order keys: inspect history/grain first')
            require(self.sources['customers'].customer_id.is_unique,'Duplicate customer keys')
            require(o.customer_id.isin(self.sources['customers'].customer_id).all(),'Unknown customer')
            for name in ['payments','shipments','returns','reviews']:require(self.sources[name].order_id.isin(o.order_id).all(),f'Orphan {name}')
            rows=[]
            for status,g in o.groupby('order_status'):
                row={'status':status,'orders':len(g)}
                for name in ['payments','shipments','returns','reviews']:row[name+'_orders']=int(g.order_id.isin(self.sources[name].order_id).sum())
                rows.append(row)
            self.status_audit=pd.DataFrame(rows);self.save('status_audit',self.status_audit)
            sp=self.sources['shipments'].copy()
            for col in ['ship_date','delivery_date']:sp[col]=pd.to_datetime(sp[col],format='%Y-%m-%d',errors='raise')
            self.shipments=sp
            j=o.merge(sp,on='order_id',how='left',validate='one_to_one');j['order_date']=pd.to_datetime(j.order_date,format='%Y-%m-%d')
            self.audit_info={'order_rows':len(o),'duplicate_order_ids':int(o.order_id.duplicated().sum()),'max_statuses_per_order':int(o.groupby('order_id').order_status.nunique().max()),'history_available':False,'shipped_with_delivery_date':int((j.order_status.eq('shipped')&j.delivery_date.notna()).sum()),'delivered_without_shipment':int((j.order_status.eq('delivered')&j.ship_date.isna()).sum()),'returned_without_detail':int((o.order_status.eq('returned')&~o.order_id.isin(self.sources['returns'].order_id)).sum()),'ship_before_order':int((j.ship_date<j.order_date).sum()),'delivery_before_ship':int((j.delivery_date<j.ship_date).sum()),'payment_positive_by_status':self.sources['payments'].assign(positive=lambda d:d.payment_value.map(Decimal).gt(0)).merge(o[['order_id','order_status']],validate='one_to_one').groupby('order_status').positive.sum().astype(int).to_dict(),'interpretation':'Do not infer completed payment or actual delivery from related fields; keep source status unchanged.'}
            return self.status_audit
    return SimpleNamespace(
        Decimal=Decimal,
        Path=Path,
        FEATURES=FEATURES,
        CUTOFF=CUTOFF,
        sha=sha,
        require=require,
        np=np,
        pd=pd,
        plt=plt,
        re=re,
        time=time,
        platform=platform,
        sklearn=sklearn,
        exact_sum=exact_sum,
        resolve_project_root=resolve_project_root,
        StandardScaler=StandardScaler,
        KMeans=KMeans,
        AgglomerativeClustering=AgglomerativeClustering,
        silhouette_score=silhouette_score,
        davies_bouldin_score=davies_bouldin_score,
        adjusted_rand_score=adjusted_rand_score,
        threadpool_limits=threadpool_limits,
        rfm=rfm,
        feature_matrix=feature_matrix,
        ScopeSteps=ScopeSteps,
    )


@cache
def segmentation_sensitivity():
    """Các bước sensitivity của bài toán phân cụm."""
    Decimal = segmentation_defaults().Decimal
    Path = segmentation_defaults().Path
    FEATURES = segmentation_defaults().FEATURES
    CUTOFF = segmentation_defaults().CUTOFF
    sha = segmentation_defaults().sha
    require = segmentation_defaults().require
    np = segmentation_defaults().np
    pd = segmentation_defaults().pd
    plt = segmentation_defaults().plt
    re = segmentation_defaults().re
    time = segmentation_defaults().time
    platform = segmentation_defaults().platform
    sklearn = segmentation_defaults().sklearn
    exact_sum = segmentation_defaults().exact_sum
    resolve_project_root = segmentation_defaults().resolve_project_root
    StandardScaler = segmentation_defaults().StandardScaler
    KMeans = segmentation_defaults().KMeans
    AgglomerativeClustering = segmentation_defaults().AgglomerativeClustering
    silhouette_score = segmentation_defaults().silhouette_score
    davies_bouldin_score = segmentation_defaults().davies_bouldin_score
    adjusted_rand_score = segmentation_defaults().adjusted_rand_score
    threadpool_limits = segmentation_defaults().threadpool_limits
    rfm = rfm_features().rfm
    feature_matrix = segmentation_transform().feature_matrix

    class SensitivitySteps:
        def sensitivity(self):
            d=self.orders;sp=self.shipments
            primary=self.selected;without=primary.loc[primary.order_id.isin(sp.order_id)]
            shipped_ids=set(sp.loc[sp.delivery_date.le(CUTOFF),'order_id'])
            expanded=d.loc[d.order_date.le(CUTOFF)&(d.order_status.eq('delivered')|(d.order_status.eq('shipped')&d.order_id.isin(shipped_ids)))]
            self.sensitivity_rows=[]
            for name,selection in [('remove_delivered_without_shipment',without),('hypothesis_add_shipped_with_delivery_date',expanded)]:
                f=rfm(selection);base=self.features.merge(f,on='customer_id',suffixes=('_base','_case'),validate='one_to_one')
                base_labels=pd.Series(self.model.labels_,index=self.features.customer_id)
                changed=f.set_index('customer_id').loc[base.customer_id].reset_index()
                x,_=feature_matrix(changed,self.key[0],self.scaler)
                with threadpool_limits(limits=1):pred=self.model.predict(x)
                y=base_labels.loc[base.customer_id].to_numpy()
                ch=np.column_stack([base[c+'_base'].astype(float).to_numpy()!=base[c+'_case'].astype(float).to_numpy() for c in FEATURES]).any(axis=1)
                row=dict(scenario=name,orders=len(selection),customers=len(f),common_customers=len(base),removed_customers=len(self.features)-len(base),added_customers=len(f)-len(base),customers_with_changed_RFM=int(ch.sum()),ari_frozen_model=float(adjusted_rand_score(y,pred)),share_changed_frozen_labels=float((y!=pred).mean()),method='Frozen primary scaler and centers, original center IDs; not refitted; expansion is hypothetical, not a status correction')
                self.sensitivity_rows.append(row)
                self.save(name+'_assignments',pd.DataFrame({'customer_id':base.customer_id,'base_center_id':y,'scenario_center_id':pred}))
            self.sensitivity_table=pd.DataFrame(self.sensitivity_rows);self.save('status_sensitivity',self.sensitivity_table)
            base=self.features.assign(center_id=self.model.labels_)
            shares=base.merge(self.behaviors[['customer_id','delivered_missing_shipment_share']],on='customer_id',validate='one_to_one').groupby('center_id').agg(customers=('customer_id','size'),missing_shipment_share_mean=('delivered_missing_shipment_share','mean'))
            self.save('dq_by_primary_center',shares.reset_index())
            return self.sensitivity_table
    return SimpleNamespace(
        Decimal=Decimal,
        Path=Path,
        FEATURES=FEATURES,
        CUTOFF=CUTOFF,
        sha=sha,
        require=require,
        np=np,
        pd=pd,
        plt=plt,
        re=re,
        time=time,
        platform=platform,
        sklearn=sklearn,
        exact_sum=exact_sum,
        resolve_project_root=resolve_project_root,
        StandardScaler=StandardScaler,
        KMeans=KMeans,
        AgglomerativeClustering=AgglomerativeClustering,
        silhouette_score=silhouette_score,
        davies_bouldin_score=davies_bouldin_score,
        adjusted_rand_score=adjusted_rand_score,
        threadpool_limits=threadpool_limits,
        rfm=rfm,
        feature_matrix=feature_matrix,
        SensitivitySteps=SensitivitySteps,
    )


@cache
def segmentation_study():
    """Analytical support for PC01–PC05; tables/figures are computed, never fabricated."""
    from pathlib import Path
    from decimal import Decimal
    import hashlib
    import numpy as np
    import pandas as pd
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    rfm = rfm_features().rfm
    feature_matrix = segmentation_transform().feature_matrix
    require = segmentation_defaults().require
    sha = segmentation_defaults().sha
    FEATURES = segmentation_defaults().FEATURES
    CUTOFF = segmentation_defaults().CUTOFF

    VN={'customer_id':'Mã khách','Recency':'Recency (ngày)','Frequency':'Frequency (đơn)','Monetary':'Monetary (ĐVT nguồn)','cluster':'Nhóm','customers':'Số khách','customer_share':'Tỷ trọng khách','Monetary_share':'Tỷ trọng Net','variant':'Thí nghiệm','k':'Số cụm','silhouette_sample':'Silhouette mẫu','davies_bouldin_full':'Davies–Bouldin toàn tập','inertia':'Inertia','min_cluster_share':'Tỷ trọng cụm nhỏ nhất','max_cluster_share':'Tỷ trọng cụm lớn nhất','seed':'Seed','ari':'ARI','rank_sum':'Tổng hạng','status':'Trạng thái','orders':'Số đơn','Recency_median':'R trung vị','Frequency_median':'F trung vị','Monetary_median':'M trung vị','Monetary_total':'Tổng Net','cancelled_share_mean':'TB tỷ trọng cancelled/khách','returned_status_share_mean':'TB tỷ trọng returned/khách','return_detail_share_mean':'TB tỷ trọng có returns/khách','missing_shipment_share_mean':'TB tỷ trọng thiếu shipment/khách','distinct_products_median':'Số SP khác nhau trung vị'}

    def share_table(frame,group):
        """Exclusive groups with original money totals, one row/customer required."""
        require(frame.customer_id.is_unique,'Customer table must be unique')
        x=frame.copy();x['Monetary']=x.Monetary.astype(float)
        t=x.groupby(group,observed=True,dropna=False).agg(customers=('customer_id','size'),Monetary_total=('Monetary','sum'),Recency_median=('Recency','median'),Frequency_median=('Frequency','median'),Monetary_median=('Monetary','median')).reset_index()
        t['customer_share']=t.customers/len(x);total=x.Monetary.sum();t['Monetary_share']=t.Monetary_total/total if total else np.nan
        return t

    def concentration(frame):
        require(frame.customer_id.is_unique,'Repeated customers distort concentration')
        values=np.sort(frame.Monetary.astype(float).to_numpy())[::-1];total=values.sum();rows=[]
        for fraction in [.01,.05,.10,.20,.50]:
            count=max(1,int(np.ceil(len(values)*fraction)))
            rows.append({'top_customer_fraction':fraction,'selected_customers':count,'monetary_share':float(values[:count].sum()/total) if total else np.nan})
        return pd.DataFrame(rows)

    def distribution(frame):
        x=frame[FEATURES].astype(float)
        d=x.describe(percentiles=[.01,.1,.25,.5,.75,.9,.95,.99]).T
        d['skew']=x.skew();d['zero_count']=x.eq(0).sum();return d.reset_index(names='feature')

    class Study:
        def __init__(self, root, part, baseline="v1"):
            self.root = Path(root)
            self.part = part
            self.model_root = self.root / "data/model/phan_khuc"
            self.base = self.model_root / baseline
            self.data = self.base
            self.records = []
            self.figure_count = 0
            self.manifest = read_model_parameters(self.base)
            self.raw_before = raw_fingerprints(self.root)
            self.f=pd.read_csv(self.data/'rfm_exact.csv',dtype={'customer_id':str,'Monetary':str},parse_dates=['first_order_date','last_order_date'])
            self.f['Monetary']=self.f.Monetary.map(Decimal)
            self.behavior=pd.read_csv(self.data/'customer_behavior.csv',dtype={'customer_id':str})
            self.scope=pd.read_csv(self.data/'customer_scope.csv',dtype={'customer_id':str})
            self.model_label=baseline
        def use_model(self,label):
            base = self.model_root / label
            m = read_model_parameters(base)
            self.model_label=label;self.modelbase=base;self.modeldata=base;self.modelmanifest=m
            self.a=pd.read_csv(self.modeldata/'customer_segments.csv',dtype={'customer_id':str})
            require(set(self.a.customer_id)==set(self.f.customer_id),'Model/customer mismatch')
            return m
        def orders(self):
            if hasattr(self,'o'):return self.o
            p = self.root / 'data/processed/orders_common.csv'
            cols=['order_id','customer_id','order_date_parsed','order_status','net_amount','delivered_missing_shipment_flag','order_before_signup_flag']
            o=pd.read_csv(p,dtype=str,keep_default_na=False,usecols=cols).rename(columns={'order_date_parsed':'order_date'})
            o['order_date'] = pd.to_datetime(o.order_date, format='%Y-%m-%d', errors='raise')
            o['net_amount'] = o.net_amount.map(Decimal)
            require(o.order_id.is_unique and o.order_id.ne('').all(), 'orders_common.csv có khóa đơn rỗng hoặc trùng')
            self.o = o
            return o
        def table(self,name,title,frame):
            self.records.append(('table',title,frame.copy()))
            from IPython.display import display
            display(frame.rename(columns=VN));return frame
        def note(self,text):
            self.records.append(('text','',text))
            from IPython.display import display,Markdown
            display(Markdown(text))
        def fig(self, name, title, figure):
            from IPython.display import display

            figure.tight_layout()
            display(figure)
            plt.close(figure)
            self.figure_count += 1

        def finish(self):
            require(
                raw_fingerprints(self.root) == self.raw_before,
                "CSV gốc thay đổi trong lượt phân tích",
            )
            result = {
                "part": self.part,
                "state": "completed",
                "model_run": self.model_label,
                "tables": sum(kind == "table" for kind, _, _ in self.records),
                "figures": self.figure_count,
            }
            print("Hoàn thành:", result)
            return result
    return SimpleNamespace(
        Path=Path,
        Decimal=Decimal,
        hashlib=hashlib,
        np=np,
        pd=pd,
        matplotlib=matplotlib,
        plt=plt,
        rfm=rfm,
        feature_matrix=feature_matrix,
        require=require,
        sha=sha,
        FEATURES=FEATURES,
        CUTOFF=CUTOFF,
        VN=VN,
        share_table=share_table,
        concentration=concentration,
        distribution=distribution,
        Study=Study,
    )


@cache
def segmentation_transform():
    """TN1/TN2 và scaler; không sửa bảng RFM đầu vào."""
    Decimal = segmentation_defaults().Decimal
    Path = segmentation_defaults().Path
    FEATURES = segmentation_defaults().FEATURES
    CUTOFF = segmentation_defaults().CUTOFF
    sha = segmentation_defaults().sha
    require = segmentation_defaults().require
    np = segmentation_defaults().np
    pd = segmentation_defaults().pd
    plt = segmentation_defaults().plt
    re = segmentation_defaults().re
    time = segmentation_defaults().time
    platform = segmentation_defaults().platform
    sklearn = segmentation_defaults().sklearn
    exact_sum = segmentation_defaults().exact_sum
    resolve_project_root = segmentation_defaults().resolve_project_root
    StandardScaler = segmentation_defaults().StandardScaler
    KMeans = segmentation_defaults().KMeans
    AgglomerativeClustering = segmentation_defaults().AgglomerativeClustering
    silhouette_score = segmentation_defaults().silhouette_score
    davies_bouldin_score = segmentation_defaults().davies_bouldin_score
    adjusted_rand_score = segmentation_defaults().adjusted_rand_score
    threadpool_limits = segmentation_defaults().threadpool_limits

    def feature_matrix(frame,variant,scaler=None):
        x=frame[FEATURES].astype(float).copy()
        require(np.isfinite(x.to_numpy()).all(),'Nonfinite model features')
        if variant=='TN2':x[['Frequency','Monetary']]=np.log1p(x[['Frequency','Monetary']])
        elif variant!='TN1':raise ValueError('Unknown experiment')
        if scaler is None:scaler=StandardScaler().fit(x)
        return scaler.transform(x),scaler
    return SimpleNamespace(
        Decimal=Decimal,
        Path=Path,
        FEATURES=FEATURES,
        CUTOFF=CUTOFF,
        sha=sha,
        require=require,
        np=np,
        pd=pd,
        plt=plt,
        re=re,
        time=time,
        platform=platform,
        sklearn=sklearn,
        exact_sum=exact_sum,
        resolve_project_root=resolve_project_root,
        StandardScaler=StandardScaler,
        KMeans=KMeans,
        AgglomerativeClustering=AgglomerativeClustering,
        silhouette_score=silhouette_score,
        davies_bouldin_score=davies_bouldin_score,
        adjusted_rand_score=adjusted_rand_score,
        threadpool_limits=threadpool_limits,
        feature_matrix=feature_matrix,
    )


@cache
def segmentation_workflow():
    """Điều phối; thuật toán được chia theo chức năng. API baseline giữ tương thích."""
    Decimal = segmentation_defaults().Decimal
    Path = segmentation_defaults().Path
    FEATURES = segmentation_defaults().FEATURES
    CUTOFF = segmentation_defaults().CUTOFF
    sha = segmentation_defaults().sha
    require = segmentation_defaults().require
    np = segmentation_defaults().np
    pd = segmentation_defaults().pd
    plt = segmentation_defaults().plt
    re = segmentation_defaults().re
    time = segmentation_defaults().time
    platform = segmentation_defaults().platform
    sklearn = segmentation_defaults().sklearn
    exact_sum = segmentation_defaults().exact_sum
    resolve_project_root = segmentation_defaults().resolve_project_root
    StandardScaler = segmentation_defaults().StandardScaler
    KMeans = segmentation_defaults().KMeans
    AgglomerativeClustering = segmentation_defaults().AgglomerativeClustering
    silhouette_score = segmentation_defaults().silhouette_score
    davies_bouldin_score = segmentation_defaults().davies_bouldin_score
    adjusted_rand_score = segmentation_defaults().adjusted_rand_score
    threadpool_limits = segmentation_defaults().threadpool_limits
    rfm = rfm_features().rfm
    FeatureSteps = rfm_features().FeatureSteps
    feature_matrix = segmentation_transform().feature_matrix
    scores = segmentation_experiments().scores
    ExperimentSteps = segmentation_experiments().ExperimentSteps
    ScopeSteps = segmentation_scope().ScopeSteps
    ProfileSteps = segmentation_profiling().ProfileSteps
    SensitivitySteps = segmentation_sensitivity().SensitivitySteps

    class Workflow(ScopeSteps,FeatureSteps,ExperimentSteps,ProfileSteps,SensitivitySteps):
        def __init__(self,root=None,label='v1'):
            self.root=resolve_project_root(root)
            require(re.fullmatch(r'[A-Za-z0-9_-]+',label) is not None,'Unsafe run label')
            self.out = self.root / 'data/model/phan_khuc' / label
            self.dataout = self.out
            require(not self.out.exists() and not self.dataout.exists(),'Run exists: choose a new label; outputs are never overwritten')
            self.raw_before = raw_fingerprints(self.root)
            self.out.mkdir(parents=True)
            self.manifest = {}

        def save(self,name,df,data=False):
            df.to_csv((self.dataout if data else self.out)/(name+'.csv'),index=False)

        def finish(self):
            require(raw_fingerprints(self.root) == self.raw_before, 'CSV gốc thay đổi trong lượt phân tích')
            require(self.assignments.customer_id.is_unique and len(self.assignments)==len(self.features),'Assignment mismatch')
            require(int(self.profiles.customers.sum())==len(self.features),'Profile population mismatch')
            require(np.isclose(self.profiles.customer_share.sum(),1),'Profile shares mismatch')
            self.manifest.update(state='completed',features=FEATURES,behavior_usage='profiling_only',selected={'variant':self.key[0],'k':self.key[1],'selection':'Top rank-sum shortlist; minimum cluster share >=1%; first candidate with mean seed ARI >=0.90. Exploratory recommendation, not proof of business effectiveness.','center_to_cluster':self.mapping,'center_coordinates':self.model.cluster_centers_.tolist(),'scaler_mean':self.scaler.mean_.tolist(),'scaler_scale':self.scaler.scale_.tolist()},raw_unchanged=True,limitations=['No state transition history or verified extraction time','No actual settlement or verified meaning of delivery_date','No automatic status correction; shipped expansion is hypothetical','Primary RFM covers delivered, not all customer activity','No CLV/churn prediction or causal marketing claims','Sampling metrics and internal indices do not establish business value','No cap or deletion of valid extreme RFM; observed history length may influence F/M','Hierarchy sample-only; DBSCAN not implemented in this baseline','Sensitivity uses frozen scaler/centers, not a refitted alternative model'])
            save_model_parameters(self.out, self.manifest['selected'])
            return self.manifest
    return SimpleNamespace(
        Decimal=Decimal,
        Path=Path,
        FEATURES=FEATURES,
        CUTOFF=CUTOFF,
        sha=sha,
        require=require,
        np=np,
        pd=pd,
        plt=plt,
        re=re,
        time=time,
        platform=platform,
        sklearn=sklearn,
        exact_sum=exact_sum,
        resolve_project_root=resolve_project_root,
        StandardScaler=StandardScaler,
        KMeans=KMeans,
        AgglomerativeClustering=AgglomerativeClustering,
        silhouette_score=silhouette_score,
        davies_bouldin_score=davies_bouldin_score,
        adjusted_rand_score=adjusted_rand_score,
        threadpool_limits=threadpool_limits,
        rfm=rfm,
        FeatureSteps=FeatureSteps,
        feature_matrix=feature_matrix,
        scores=scores,
        ExperimentSteps=ExperimentSteps,
        ScopeSteps=ScopeSteps,
        ProfileSteps=ProfileSteps,
        SensitivitySteps=SensitivitySteps,
        Workflow=Workflow,
    )
