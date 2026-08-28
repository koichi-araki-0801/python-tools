# graph-editor フロント JS テスト移植 対応表(vitest → pytest)

実行エンジン差: 旧 = playwright 同梱 chromium / 新 = Edge channel(同系エンジン・版は端末 Edge 追随)。

| 旧(vitest/TS) | 新(pytest) | 状態 |
|---|---|---|
| editor_leader_geom.test.ts: clampPointToBox 左外の点は左辺へ(外枠上の最近点) | test_grapheditor_leader_geom_js.py::test_clamp_left_outside_point_goes_to_left_edge | 移植済み |
| editor_leader_geom.test.ts: clampPointToBox 右外の点は右辺へ | test_grapheditor_leader_geom_js.py::test_clamp_right_outside_point_goes_to_right_edge | 移植済み |
| editor_leader_geom.test.ts: clampPointToBox 上外の点は上辺へ(SVG: 上が小さい y) | test_grapheditor_leader_geom_js.py::test_clamp_top_outside_point_goes_to_top_edge | 移植済み |
| editor_leader_geom.test.ts: clampPointToBox 下外の点は下辺へ | test_grapheditor_leader_geom_js.py::test_clamp_bottom_outside_point_goes_to_bottom_edge | 移植済み |
| editor_leader_geom.test.ts: clampPointToBox 斜め外の点は角へクランプ | test_grapheditor_leader_geom_js.py::test_clamp_diagonal_outside_point_clamps_to_corner | 移植済み |
| editor_leader_geom.test.ts: clampPointToBox 矩形内の点はそのまま(= 矩形内なら点自身) | test_grapheditor_leader_geom_js.py::test_clamp_point_inside_box_stays_as_is | 移植済み |
| editor_leader_geom.test.ts: parsePath/buildPath M…L… を点列へ | test_grapheditor_leader_geom_js.py::test_parsepath_reads_m_l_into_points | 移植済み |
| editor_leader_geom.test.ts: parsePath/buildPath 点列を M…L… へ | test_grapheditor_leader_geom_js.py::test_buildpath_writes_points_into_m_l | 移植済み |
| editor_leader_geom.test.ts: parsePath/buildPath 往復で一致する | test_grapheditor_leader_geom_js.py::test_parsepath_buildpath_roundtrip | 移植済み |
| editor_leader_geom.test.ts: parsePath/buildPath 負数・小数・指数表記を読む | test_grapheditor_leader_geom_js.py::test_parsepath_reads_negative_decimal_exponent | 移植済み |
| editor_leader_geom.test.ts: parsePath/buildPath 空文字や数値なしは空配列 | test_grapheditor_leader_geom_js.py::test_parsepath_empty_or_no_numbers_is_empty_array | 移植済み |
| editor_leader_geom.test.ts: parsePath/buildPath 座標が奇数個なら最後の余りは無視 | test_grapheditor_leader_geom_js.py::test_parsepath_odd_count_coordinates_drops_remainder | 移植済み |
| editor_leader_geom.test.ts: parseTranslate translate(dx,dy) を読む | test_grapheditor_leader_geom_js.py::test_parsetranslate_reads_translate_dx_dy | 移植済み |
| editor_leader_geom.test.ts: parseTranslate 空白・負数・小数を許容 | test_grapheditor_leader_geom_js.py::test_parsetranslate_allows_whitespace_negative_decimal | 移植済み |
| editor_leader_geom.test.ts: parseTranslate 空/不正は原点 | test_grapheditor_leader_geom_js.py::test_parsetranslate_empty_or_invalid_is_origin | 移植済み |
| editor_leader_geom.test.ts: parseTranslate 先頭ドット数値も従来どおり読む(数値集合の不変) | test_grapheditor_leader_geom_js.py::test_parsetranslate_reads_leading_dot_numbers | 移植済み |
| editor_leader_geom.test.ts: parseTranslate 閉じ括弧に至れない巨大な transform でも即座に返る(ReDoS 回帰) | test_grapheditor_leader_geom_js.py::test_parsetranslate_redos_guard_returns_immediately | 移植済み |
| editor_leader_geom.test.ts: normColor white/#fff → #ffffff | test_grapheditor_leader_geom_js.py::test_normcolor_white_and_hex_shorthand | 移植済み |
| editor_leader_geom.test.ts: normColor black/#000 → #000000 | test_grapheditor_leader_geom_js.py::test_normcolor_black_and_hex_shorthand | 移植済み |
| editor_leader_geom.test.ts: normColor 前後空白を除去し小文字化 | test_grapheditor_leader_geom_js.py::test_normcolor_trims_whitespace_and_lowercases | 移植済み |
| editor_leader_geom.test.ts: normColor null はそのまま | test_grapheditor_leader_geom_js.py::test_normcolor_null_stays_null | 移植済み |
| editor_pie_rules.test.ts: parsePieGeometry 楔形パス(M…L…A)から中心と半径を取り出す | test_grapheditor_pie_rules_js.py::test_parsepiegeometry_wedge_path_extracts_center_and_radius | 移植済み |
| editor_pie_rules.test.ts: parsePieGeometry 空白区切り・負座標も許容する | test_grapheditor_pie_rules_js.py::test_parsepiegeometry_allows_whitespace_and_negative_coords | 移植済み |
| editor_pie_rules.test.ts: parsePieGeometry A の無いパス(円弧なし)は null | test_grapheditor_pie_rules_js.py::test_parsepiegeometry_no_arc_is_null | 移植済み |
| editor_pie_rules.test.ts: parsePieGeometry L の無い全円パス(100% 単一スライス)は null | test_grapheditor_pie_rules_js.py::test_parsepiegeometry_full_circle_without_l_is_null | 移植済み |
| editor_pie_rules.test.ts: parsePieGeometry L が A より後ろにしか無いパスも null(楔形の並びでない) | test_grapheditor_pie_rules_js.py::test_parsepiegeometry_l_only_after_a_is_null | 移植済み |
| editor_pie_rules.test.ts: fallbackPieGeometry キャンバス中央・短辺 × ratio | test_grapheditor_pie_rules_js.py::test_fallbackpiegeometry_canvas_center_short_side_times_ratio | 移植済み |
| editor_pie_rules.test.ts: labelBox/labelCenter textTx を反映した外枠を組む | test_grapheditor_pie_rules_js.py::test_labelbox_reflects_texttx_into_frame | 移植済み |
| editor_pie_rules.test.ts: labelBox/labelCenter 中心点は bbox 中央 + textTx | test_grapheditor_pie_rules_js.py::test_labelcenter_is_bbox_center_plus_texttx | 移植済み |
| editor_pie_rules.test.ts: isOutsidePie 円内は false / 円外は true(境界ちょうどは内側扱い) | test_grapheditor_pie_rules_js.py::test_isoutsidepie_inside_false_outside_true_boundary_is_inside | 移植済み |
| editor_pie_rules.test.ts: computeDefaultLeaderPts 端点はラベル外枠上で円中心に最も近い点 | test_grapheditor_pie_rules_js.py::test_computedefaultleaderpts_endpoint_is_closest_point_on_label_frame | 移植済み |
| editor_pie_rules.test.ts: computeDefaultLeaderPts anchor 未取得(null)は中心→端点方向のリム点へ退避する | test_grapheditor_pie_rules_js.py::test_computedefaultleaderpts_null_anchor_falls_back_to_center_to_endpoint_direction | 移植済み |
| editor_pie_rules.test.ts: computeDefaultLeaderPts 端点が円中心と一致する退避時は右向きへ既定化する(零ベクトル防御) | test_grapheditor_pie_rules_js.py::test_computedefaultleaderpts_zero_vector_escape_defaults_to_rightward | 移植済み |
| editor_pie_rules.test.ts: parsePieGeometry は入力長に対して線形 正当な d は今までどおり解釈できる | test_grapheditor_pie_rules_js.py::test_parsepiegeometry_valid_d_still_parses_as_before | 移植済み |
| editor_pie_rules.test.ts: parsePieGeometry は入力長に対して線形 長い数字列でも所要が二乗で伸びない | test_grapheditor_pie_rules_js.py::test_parsepiegeometry_long_digit_run_does_not_grow_quadratically | 移植済み |
| editor_svg_policy.test.ts: isAllowedElement 能動コンテンツを持ち込める要素は SVG 名前空間でも通さない | test_grapheditor_svg_policy_js.py::test_isallowedelement_active_content_capable_elements_never_allowed_even_in_svg_ns | 移植済み |
| editor_svg_policy.test.ts: isAllowedElement 許可済みの綴りでも名前空間が違えば通さない(プレフィックスでの持ち込み対策) | test_grapheditor_svg_policy_js.py::test_isallowedelement_allowed_spelling_wrong_namespace_not_allowed | 移植済み |
| editor_svg_policy.test.ts: isAllowedElement 大小文字を畳まない(畳むと綴り替えが通る/正常系の綴りが壊れる) | test_grapheditor_svg_policy_js.py::test_isallowedelement_does_not_fold_case | 移植済み |
| editor_svg_policy.test.ts: isAllowedElement pie-chart 実出力の 8 要素は通る | test_grapheditor_svg_policy_js.py::test_isallowedelement_pie_chart_output_8_elements_allowed | 移植済み |
| editor_svg_policy.test.ts: isAllowedAttr 名前空間つき属性は URI だけを見て一律に落とす(プレフィックス比較をしない) | test_grapheditor_svg_policy_js.py::test_isallowedattr_namespaced_attrs_dropped_by_uri_only_no_prefix_compare | 移植済み |
| editor_svg_policy.test.ts: isAllowedAttr URL を値に取る属性とイベント属性は許可集合に無い | test_grapheditor_svg_policy_js.py::test_isallowedattr_url_and_event_attrs_not_in_allowed_set | 移植済み |
| editor_svg_policy.test.ts: isAllowedAttr 綴りは完全一致(`viewBox` を畳むと正常系が壊れる) | test_grapheditor_svg_policy_js.py::test_isallowedattr_exact_spelling_match | 移植済み |
| editor_svg_policy.test.ts: isAllowedAttr `data-*` は通すが、エディタ専有名だけは通さない | test_grapheditor_svg_policy_js.py::test_isallowedattr_data_star_allowed_except_editor_reserved_names | 移植済み |
| editor_svg_policy.test.ts: isAllowedAttr `type` は `<style>` の 1 箇所だけ | test_grapheditor_svg_policy_js.py::test_isallowedattr_type_only_on_style | 移植済み |
| editor_svg_policy.test.ts: sanitizeAttrValue paint 属性はスキームつきの値も `url()` 参照も受理しない | test_grapheditor_svg_policy_js.py::test_sanitizeattrvalue_paint_rejects_schemed_values_and_url_refs | 移植済み |
| editor_svg_policy.test.ts: sanitizeAttrValue pie-chart 実出力の paint 値は受理する | test_grapheditor_svg_policy_js.py::test_sanitizeattrvalue_pie_chart_output_paint_values_accepted | 移植済み |
| editor_svg_policy.test.ts: sanitizeAttrValue `<style type>` は `text/css` のみ | test_grapheditor_svg_policy_js.py::test_sanitizeattrvalue_style_type_only_text_css | 移植済み |
| editor_svg_policy.test.ts: sanitizeAttrValue 制御文字を含む値と長すぎる値は落とす | test_grapheditor_svg_policy_js.py::test_sanitizeattrvalue_control_chars_and_too_long_values_dropped | 移植済み |
| editor_svg_policy.test.ts: sanitizeAttrValue それ以外の属性値は素通しする(URL 属性が 1 つも残らないため) | test_grapheditor_svg_policy_js.py::test_sanitizeattrvalue_other_attrs_pass_through | 移植済み |
| editor_svg_policy.test.ts: safeCssColor 宣言の継ぎ足し・markup 脱出・関数呼び出しを落とす | test_grapheditor_svg_policy_js.py::test_safecsscolor_drops_declaration_splice_markup_escape_and_function_calls | 移植済み |
| editor_svg_policy.test.ts: safeCssColor 色として妥当な書式だけ受理する | test_grapheditor_svg_policy_js.py::test_safecsscolor_accepts_only_valid_color_syntax | 移植済み |
| editor_svg_policy.test.ts: sanitizeFontFaceCss 外部フェッチを立てる CSS は 1 つも受理しない | test_grapheditor_svg_policy_js.py::test_sanitizefontfacecss_rejects_all_css_that_sets_up_external_fetch | 移植済み |
| editor_svg_policy.test.ts: sanitizeFontFaceCss `@import` を消すだけの denylist では抜ける形を、全消費マッチで落とす | test_grapheditor_svg_policy_js.py::test_sanitizefontfacecss_full_consume_match_catches_what_denylist_would_miss | 移植済み |
| editor_svg_policy.test.ts: sanitizeFontFaceCss 受理ブロックの後ろに 1 バイトでも残れば全体を捨てる | test_grapheditor_svg_policy_js.py::test_sanitizefontfacecss_discards_whole_input_if_even_one_byte_remains | 移植済み |
| editor_svg_policy.test.ts: sanitizeFontFaceCss base64 の charset を縛り `)` での早期クローズを塞ぐ | test_grapheditor_svg_policy_js.py::test_sanitizefontfacecss_constrains_base64_charset_blocks_early_close_via_paren | 移植済み |
| editor_svg_policy.test.ts: sanitizeFontFaceCss 認識できない宣言が 1 つでもあればブロックごと捨てる | test_grapheditor_svg_policy_js.py::test_sanitizefontfacecss_discards_whole_block_if_any_declaration_unrecognized | 移植済み |
| editor_svg_policy.test.ts: sanitizeFontFaceCss 宣言名がプロトタイプ由来の語でも、例外ではなく拒否で返す | test_grapheditor_svg_policy_js.py::test_sanitizefontfacecss_declaration_names_from_prototype_words_rejected_not_thrown | 移植済み |
| editor_svg_policy.test.ts: sanitizeFontFaceCss pie-chart 実出力の `@font-face` はバイト単位で受理し、再適用でも変わらない | test_grapheditor_svg_policy_js.py::test_sanitizefontfacecss_pie_chart_output_accepted_byte_for_byte_and_idempotent | 移植済み |
| editor_svg_policy.test.ts: @font-face の値検証は入力長に対して線形 正当な font-family は今までどおり通る | test_grapheditor_svg_policy_js.py::test_sanitizefontfacecss_valid_font_family_still_passes | 移植済み |
| editor_svg_policy.test.ts: @font-face の値検証は入力長に対して線形 区切りを 16 倍にしても所要は跳ね上がらない | test_grapheditor_svg_policy_js.py::test_sanitizefontfacecss_16x_delimiters_time_does_not_spike | 移植済み |
| editor_state_fields.test.ts: stateEquals 初期スナップショットとの比較結果が旧実装(直列化比較)と一致する | test_grapheditor_utils_js.py::test_stateequals_matches_legacy_serialize_compare_against_initial_snapshot | 移植済み |
| editor_state_fields.test.ts: stateEquals 等しい状態は等しい/1 フィールドでも違えば等しくない | test_grapheditor_utils_js.py::test_stateequals_equal_states_equal_any_single_field_diff_not_equal | 移植済み |
| editor_state_fields.test.ts: stateEquals 片方が欠けていれば等しくないと判定する(未読込との取り違え防止) | test_grapheditor_utils_js.py::test_stateequals_either_side_missing_is_not_equal | 移植済み |
| editor_state_fields.test.ts: stateEquals `fill` の未設定(null)同士は等しく、片側だけ null なら等しくない | test_grapheditor_utils_js.py::test_stateequals_fill_null_on_both_sides_equal_one_side_only_not_equal | 移植済み |
| editor_state_fields.test.ts: stateEquals _auto は STATE_FIELDS に含まれ、snapshot/apply で往復する | test_grapheditor_utils_js.py::test_stateequals_auto_field_is_in_state_fields_and_roundtrips_via_snapshot | 移植済み |
| editor_state_fields.test.ts: stateEquals 全フィールドに等値判定がある(項目追加時の付け忘れを落とす) | test_grapheditor_utils_js.py::test_stateequals_every_field_has_copy_and_equals | 移植済み |
| editor_shortcuts.test.ts: acceptsShortcut 入力欄にフォーカスがある間はどの範囲も受理しない | test_grapheditor_utils_js.py::test_acceptsshortcut_no_scope_accepted_while_input_focused | 移植済み |
| editor_shortcuts.test.ts: acceptsShortcut 文書に紐づく操作は編集画面(手順 2)でのみ受理する | test_grapheditor_utils_js.py::test_acceptsshortcut_document_scope_accepted_only_at_phase2 | 移植済み |
| editor_shortcuts.test.ts: acceptsShortcut 保存は編集画面と保存画面で、開くはどの手順でも受理する | test_grapheditor_utils_js.py::test_acceptsshortcut_save_at_phase2_and_3_open_at_any_phase | 移植済み |
| editor_shortcuts.test.ts: acceptsShortcut フォーカス要素が無くても判定できる(手順だけで決まる) | test_grapheditor_utils_js.py::test_acceptsshortcut_works_without_focus_element | 移植済み |
| editor_label_text.test.ts: extractPercentText 2 行構成では % 行の表示文字列をそのまま採り、data-percent から作り直さない | test_grapheditor_utils_js.py::test_extractpercenttext_two_row_uses_displayed_percent_row_verbatim | 移植済み |
| editor_label_text.test.ts: extractPercentText 1 行構成では名前の分だけを落として % 部分を採る | test_grapheditor_utils_js.py::test_extractpercenttext_one_row_drops_name_prefix_and_keeps_percent | 移植済み |
| editor_label_text.test.ts: extractPercentText 行数 1 と 2 を往復しても表示文字列が変わらない | test_grapheditor_utils_js.py::test_extractpercenttext_stable_across_1_and_2_row_roundtrip | 移植済み |
| editor_label_text.test.ts: extractPercentText % が表示されていないラベルは空文字(data-percent があっても足さない) | test_grapheditor_utils_js.py::test_extractpercenttext_no_percent_displayed_returns_empty | 移植済み |
| editor_label_text.test.ts: extractPercentText 表示文字列から読み取れないときだけ data-percent を保険に使う | test_grapheditor_utils_js.py::test_extractpercenttext_falls_back_to_data_percent_only_when_unreadable | 移植済み |
| editor_drag.e2e.ts: 文字を円の周囲へ動かしても引出線端点は常に外枠上 (手動 leader) | test_grapheditor_e2e_drag.py::test_move_label_around_pie_endpoint_always_on_frame_manual_leader | 移植済み |
| editor_drag.e2e.ts: 円外で自動生成された引出線端点も外枠上、円内へ戻すと自動削除 (位置駆動) | test_grapheditor_e2e_drag.py::test_auto_leader_outside_pie_endpoint_on_frame_and_removed_when_back_inside | 移植済み |
| editor_drag.e2e.ts: 行数・長体でラベル寸法が変わっても引出線端点は外枠上へ戻る | test_grapheditor_e2e_drag.py::test_label_frame_change_by_line_count_and_condense_endpoint_returns_to_frame | 移植済み |
| editor_load_guards.e2e.ts: ラベル数の上限を超える SVG は読込ごと拒否し、件数を通知する | test_grapheditor_e2e_load_guards.py::test_over_label_limit_svg_rejected_wholesale_with_count_notified | 移植済み |
| editor_load_guards.e2e.ts: 上限内のラベル数は従来どおり読める (上限が実用範囲を切らない) | test_grapheditor_e2e_load_guards.py::test_label_count_within_limit_loads_as_before | 移植済み |
| editor_load_guards.e2e.ts: ノード数の上限を超える SVG は解釈不能として拒否する | test_grapheditor_e2e_load_guards.py::test_over_node_limit_svg_rejected_as_uninterpretable | 移植済み |
| editor_load_guards.e2e.ts: 読込を中断しても前のファイルの図・状態がキャンバスに残らない | test_grapheditor_e2e_load_guards.py::test_aborted_load_leaves_no_previous_file_state_on_canvas | 移植済み |
| editor_load_guards.e2e.ts: @font-face の宣言名がプロトタイプ由来の語でも読込は完走する | test_grapheditor_e2e_load_guards.py::test_font_face_declaration_names_from_prototype_words_still_completes_load | 移植済み |
| editor_load_guards.e2e.ts: 読込を中断したらレールの「編集中」マークが残らない | test_grapheditor_e2e_load_guards.py::test_aborted_load_leaves_no_editing_mark_on_the_rail | 移植済み |
| editor_ops.e2e.ts: Undo/Redo がラベル位置を往復し、新規操作で redo 分岐を破棄する | test_grapheditor_e2e_ops.py::test_undo_redo_round_trips_label_position_and_new_op_discards_redo_branch | 移植済み |
| editor_ops.e2e.ts: 保存 bake: transform 焼き込み・編集用要素の除去・元サイズ復元 | test_grapheditor_e2e_ops.py::test_save_bake_burns_in_transform_removes_editor_elements_restores_original_size | 移植済み |
| editor_ops.e2e.ts: インスペクタの実クリックで leader 追加・曲げ点・行数・文字色・リセットが配線されている | test_grapheditor_e2e_ops.py::test_inspector_real_clicks_wire_leader_add_bend_lines_fill_reset | 移植済み |
| editor_ops.e2e.ts: 未保存の調整があるファイルからレールで切替えると確認し、キャンセルで編集を保つ | test_grapheditor_e2e_ops.py::test_switching_files_from_rail_with_unsaved_edits_confirms_and_cancel_keeps_edits | 移植済み |
| editor_ops.e2e.ts: 未保存の調整が無ければファイル切替に確認を挟まない | test_grapheditor_e2e_ops.py::test_switching_files_without_unsaved_edits_does_not_prompt | 移植済み |
| editor_ops.e2e.ts: ショートカットは手順とフォーカスで受理を絞り、矢印のリピートは履歴を積み増さない | test_grapheditor_e2e_ops.py::test_shortcuts_gate_by_step_and_focus_and_arrow_repeat_does_not_pile_up_history | 移植済み |
| editor_sanitize.e2e.ts: foreignObject の XHTML iframe が取り込まれず srcdoc も走らない | test_grapheditor_e2e_sanitize.py::test_foreignobject_xhtml_iframe_not_taken_in_and_srcdoc_does_not_run | 移植済み |
| editor_sanitize.e2e.ts: animate による href 差し替えが要素ごと落ちる | test_grapheditor_e2e_sanitize.py::test_animate_href_swap_drops_the_whole_element | 移植済み |
| editor_sanitize.e2e.ts: 別プレフィックスの xlink も制御文字入りスキームも、名前空間つき属性ごと落ちる | test_grapheditor_e2e_sanitize.py::test_alternate_prefix_xlink_and_control_char_scheme_drop_the_whole_namespaced_attr | 移植済み |
| editor_sanitize.e2e.ts: 外部 URL を参照する image / @import / @font-face でも外部リクエストが飛ばない | test_grapheditor_e2e_sanitize.py::test_external_url_image_import_font_face_do_not_fire_external_requests | 移植済み |
| editor_sanitize.e2e.ts: スライスの fill から属性を閉じても、インスペクタへ要素を注入できない | test_grapheditor_e2e_sanitize.py::test_fill_closing_the_attribute_cannot_inject_an_element_into_the_inspector | 移植済み |
| editor_sanitize.e2e.ts: 正当な fill はこれまでどおり swatch に反映される | test_grapheditor_e2e_sanitize.py::test_legit_fill_is_reflected_in_the_swatch_as_before | 移植済み |
| editor_sanitize.e2e.ts: 取り込み後の DOM は ELEMENT と TEXT 以外のノードを持たない | test_grapheditor_e2e_sanitize.py::test_ingested_dom_has_no_nodes_other_than_element_and_text | 移植済み |
| editor_sanitize.e2e.ts: 保存出力は能動コンテンツを持ち越さず、再読込しても 1 件も除去されない | test_grapheditor_e2e_sanitize.py::test_saved_output_carries_no_active_content_and_reload_removes_nothing | 移植済み |
| editor_sanitize.e2e.ts: 許可外を含む入力では除去件数が 0 にならず、利用者に知らされる | test_grapheditor_e2e_sanitize.py::test_input_with_disallowed_content_never_reports_zero_removed_and_user_is_told | 移植済み |
| editor_sanitize.e2e.ts: SVG として解釈できない入力は null(読み込みを中断する) | test_grapheditor_e2e_sanitize.py::test_input_that_cannot_be_parsed_as_svg_is_null_load_aborts | 移植済み |
| editor_sanitize.e2e.ts: pie-chart 実出力は 1 件も削られず、フォント・data-* ・textLength が保たれる | test_grapheditor_e2e_sanitize.py::test_real_pie_chart_output_nothing_removed_font_data_star_textlength_preserved | 移植済み |
| editor_sanitize.e2e.ts: 選択マーカーが列挙漏れで残っても、予約 data-editor-sel を出口 sanitizeSvg が検知する | test_grapheditor_e2e_sanitize.py::test_selection_marker_missed_by_removal_list_is_still_caught_by_reserved_data_editor_sel | 移植済み |
| editor_sanitize.e2e.ts: sanitizeSvg が例外を投げても save は保存を中止し、ダウンロードを起こさない | test_grapheditor_e2e_sanitize.py::test_sanitizesvg_throwing_makes_save_abort_and_not_trigger_a_download | 移植済み |
| editor_sanitize.e2e.ts: 往復: 保存出力を再度開いても除去 0・ラベル数一致・transform が焼き込まれている | test_grapheditor_e2e_sanitize.py::test_round_trip_reopening_saved_output_zero_removed_same_label_count_transform_baked_in | 移植済み |
| capture_docs.e2e.ts: capture open_screen(手順1) | test_grapheditor_e2e_capture_docs.py::test_capture_open_screen | 移植済み(出力先を docs/graph-editor/images → tmp_path へ変更。理由は同ファイル docstring) |
| capture_docs.e2e.ts: capture editor_main(手順2 全体) | test_grapheditor_e2e_capture_docs.py::test_capture_editor_main | 移植済み(出力先を docs/graph-editor/images → tmp_path へ変更。理由は同ファイル docstring) |
| capture_docs.e2e.ts: capture handles_zoom / condense_zoom(ハンドルと長体の拡大) | test_grapheditor_e2e_capture_docs.py::test_capture_handles_zoom_condense_zoom | 移植済み(出力先を docs/graph-editor/images → tmp_path へ変更。理由は同ファイル docstring) |
| capture_docs.e2e.ts: capture panel_right(右パネル) | test_grapheditor_e2e_capture_docs.py::test_capture_panel_right | 移植済み(出力先を docs/graph-editor/images → tmp_path へ変更。理由は同ファイル docstring) |
| capture_docs.e2e.ts: capture save_screen(手順3) | test_grapheditor_e2e_capture_docs.py::test_capture_save_screen | 移植済み(出力先を docs/graph-editor/images → tmp_path へ変更。理由は同ファイル docstring) |
