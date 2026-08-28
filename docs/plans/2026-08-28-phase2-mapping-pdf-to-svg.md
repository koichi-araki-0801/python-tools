# PdfToSvg フロント JS テスト移植 対応表(vitest → pytest)

実行エンジン差: 旧 = playwright 同梱 chromium / 新 = Edge channel(同系エンジン・版は端末 Edge 追随)。

| 旧(vitest/TS) | 新(pytest) | 状態 |
|---|---|---|
| geometry.test.js: parseSpec 範囲と単発を昇順ユニークに展開する | test_pdftosvg_geometry_js.py::test_parsespec_expands_ranges_and_singles | 移植済み |
| geometry.test.js: parseSpec 逆順の範囲は正順に直す | test_pdftosvg_geometry_js.py::test_parsespec_normalizes_reversed_range | 移植済み |
| geometry.test.js: parseSpec 重複は 1 つにまとめる | test_pdftosvg_geometry_js.py::test_parsespec_dedupes | 移植済み |
| geometry.test.js: parseSpec 1..maxPages にクランプする | test_pdftosvg_geometry_js.py::test_parsespec_clamps_to_1_maxpages | 移植済み |
| geometry.test.js: parseSpec 空文字・不正トークンは無視する | test_pdftosvg_geometry_js.py::test_parsespec_ignores_empty_and_invalid_tokens | 移植済み |
| geometry.test.js: clientToPage 要素左上のクライアント座標は viewBox 原点へ写る | test_pdftosvg_geometry_js.py::test_clienttopage_top_left_maps_to_viewbox_origin | 移植済み |
| geometry.test.js: clientToPage 中心は viewBox 中心へ写る(スケール 2 倍) | test_pdftosvg_geometry_js.py::test_clienttopage_center_maps_to_viewbox_center_scale_2x | 移植済み |
| state.test.js: 純粋ヘルパ counts は状態別に集計する | test_pdftosvg_state_js.py::test_pure_helpers_counts_tallies_by_status | 移植済み |
| state.test.js: 純粋ヘルパ pass は all で常に通し、それ以外は一致のみ | test_pdftosvg_state_js.py::test_pure_helpers_pass_all_always_passes_others_match_only | 移植済み |
| state.test.js: 純粋ヘルパ initStatus は changed から pending/none を導出する | test_pdftosvg_state_js.py::test_pure_helpers_initstatus_derives_pending_none_from_changed | 移植済み |
| state.test.js: applyState FILE_START を累積ページ数で組む | test_pdftosvg_state_js.py::test_applystate_file_start_is_cumulative_page_counts | 移植済み |
| state.test.js: applyState status を changed から初期化し、キャッシュを破棄する | test_pdftosvg_state_js.py::test_applystate_initializes_status_from_changed_and_discards_caches | 移植済み |
| state.test.js: applyState ページ数減少時は現在ページを 0 へ戻す | test_pdftosvg_state_js.py::test_applystate_resets_current_page_when_page_count_shrinks | 移植済み |
| state.test.js: applyState 同一ページ列の再取得は確認状態(reviewed/skipped/pending)を保持する | test_pdftosvg_state_js.py::test_applystate_reload_of_same_page_list_preserves_confirmation_status | 移植済み |
| state.test.js: applyState changed2 が false→true になったページは pending、true→false は none へ倒す | test_pdftosvg_state_js.py::test_applystate_toggles_status_to_pending_or_none_on_changed_flip | 移植済み |
| state.test.js: applyState ページ列が異なる(ファイル追加・削除)ときは initStatus で作り直す | test_pdftosvg_state_js.py::test_applystate_rebuilds_status_via_initstatus_when_page_list_differs | 移植済み |
| state.test.js: applyState ページ列が変わったらレール選択とファイル折り畳みも捨てる | test_pdftosvg_state_js.py::test_applystate_discards_rail_selection_and_file_collapse_when_page_list_changes | 移植済み |
| state.test.js: applyState 同一ページ列の再取得では選択と折り畳みを保つ | test_pdftosvg_state_js.py::test_applystate_reload_of_same_page_list_preserves_selection_and_collapse | 移植済み |
| state.test.js: invalidateAll 全ページの SVG キャッシュを捨てる | test_pdftosvg_state_js.py::test_invalidateall_discards_svg_cache_for_all_pages | 移植済み |
| state.test.js: 導出 statusArr/changedArr は phase で切り替わる | test_pdftosvg_state_js.py::test_derived_statusarr_changedarr_switch_by_phase | 移植済み |
| state.test.js: 導出 pkey/curElSel は現在ページの fi:pi をキーにする | test_pdftosvg_state_js.py::test_derived_pkey_curelsel_key_by_current_page_fi_pi | 移植済み |
| state.test.js: 導出 selKeys/selCount/clearSel は現在 phase の選択のみ扱う | test_pdftosvg_state_js.py::test_derived_selkeys_selcount_clearsel_scope_to_current_phase | 移植済み |
| state.test.js: 導出 statusOfCur は現在ページの状態を返す | test_pdftosvg_state_js.py::test_derived_statusofcur_returns_status_of_current_page | 移植済み |
| state.test.js: 遷移 nextPending は現在位置の先を優先し、末尾まで無ければ先頭へ巻き戻る | test_pdftosvg_state_js.py::test_transition_nextpending_prefers_ahead_and_wraps_to_start | 移植済み |
| state.test.js: 遷移 firstPending は先頭から探し、無ければ 0 | test_pdftosvg_state_js.py::test_transition_firstpending_searches_from_start_default_zero | 移植済み |
| state.test.js: 遷移 advancePhase は 2→3(page リセット)→4 と進み、ガードと遷移先の選択を解除する | test_pdftosvg_state_js.py::test_transition_advancephase_moves_2_to_3_to_4_and_clears_guard_and_target_selection | 移植済み |
| state.test.js: 書き出し範囲 all は全ページ | test_pdftosvg_state_js.py::test_export_range_all_mode_is_all_pages | 移植済み |
| state.test.js: 書き出し範囲 noskip はどちらかの手順でスキップしたページを除く | test_pdftosvg_state_js.py::test_export_range_noskip_excludes_pages_skipped_in_either_step | 移植済み |
| state.test.js: 書き出し範囲 spec は指定ファイル内のページ番号列を fileIndex 付きで返す | test_pdftosvg_state_js.py::test_export_range_spec_mode_returns_pages_in_target_file_with_file_index | 移植済み |
| state.test.js: 書き出し範囲 expCount は page モードで 1(ページがあれば) | test_pdftosvg_state_js.py::test_export_range_expcount_is_one_in_page_mode_when_pages_exist | 移植済み |
| state.test.js: 書き出し範囲 zipName は単一ファイル由来なら元名を継ぎ、混在なら汎用名 | test_pdftosvg_state_js.py::test_export_range_zipname_keeps_source_name_or_generic_when_mixed | 移植済み |
| state.test.js: ZIP 送信の分割 予算に収まる塊へ順に分ける | test_pdftosvg_state_js.py::test_zip_chunking_splits_into_budget_sized_chunks_in_order | 移植済み |
| state.test.js: ZIP 送信の分割 単独で予算を超える 1 件はその 1 件だけの塊にする(落とさない) | test_pdftosvg_state_js.py::test_zip_chunking_keeps_single_oversized_item_as_its_own_chunk | 移植済み |
| state.test.js: ZIP 送信の分割 空なら塊も無い | test_pdftosvg_state_js.py::test_zip_chunking_empty_input_yields_no_chunks | 移植済み |
| app_flow.e2e.ts: 4 ステップ通し: 取込 → 置換 → 削除/Undo → 書き出し | test_pdftosvg_app_flow_e2e.py::test_four_step_flow | 移植済み |
| app_flow.e2e.ts: ページ切替: 遅れて届いた旧ページの取得結果が現ページの操作を壊さない | test_pdftosvg_app_flow_e2e.py::test_stale_page_fetch_does_not_break_current_page | 移植済み |
| app_flow.e2e.ts: 読み込みが途中で失敗しても、成功した分は取り込んで理由を知らせる | test_pdftosvg_app_flow_e2e.py::test_partial_load_failure_keeps_succeeded_files | 移植済み |
| app_flow.e2e.ts: 一覧の取得に失敗したら旧ページの行を残さず、再試行の導線を出す | test_pdftosvg_app_flow_e2e.py::test_list_fetch_failure_clears_rows_and_offers_retry | 移植済み |
