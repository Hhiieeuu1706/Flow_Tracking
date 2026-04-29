# EXPLORATORY REPORT: USTEC FLOW-PRICE DYNAMICS
**Subject**: Investigating Flow-Strength Transitions as Indicators of Market Regime  
**Asset**: USTEC (Nasdaq 100 Index)  
**Scope**: 199 Merged Observations (Exploratory Phase)

---

## 1. Executive Summary
Nghiên cứu này khám phá liệu các biến động trong cấu trúc dòng tiền (Flow-strength dynamics) có cung cấp thông tin hữu ích về các điều kiện thị trường ngắn hạn hay không. Kết quả sơ bộ gợi ý rằng các tín hiệu Flow có khả năng **nhận diện các giai đoạn thị trường biến động mạnh hoặc mất ổn định**, thay vì đóng vai trò là một công cụ dự báo hướng đi (directional forecast) thuần túy. Do kích thước mẫu còn hạn chế và ý nghĩa thống kê chưa cao (p > 0.3), các quan sát trong báo cáo này được trình bày dưới dạng **đề xuất giả thuyết (Hypothesis generation)** để tiếp tục kiểm chứng trong tương lai.

## 2. Methodology & Algorithm Framework
### 2.1 The Heuristic Flow Engine
The system maps multi-asset macro data into a scalar flow index $S_t \in [-10, 10]$, where each component (direction, speed, delta) contributes deterministically to the final score through a fixed heuristic transformation.

#### A. Multi-Dimensional Quantization
Mỗi tài sản vĩ mô được lượng hóa hàng ngày qua 3 chiều:
- **Direction**: Dựa trên nến ngày (Close vs Open).
- **Speed**: Phân loại dựa trên phân vị biên độ (Range Quantile) 5 ngày gần nhất.
- **$\Delta$Speed (Acceleration)**: Tỷ lệ Range hiện tại / Median Range 5 ngày. Đây là hệ số nhân (**Modifier**): *Acceleration (1.2x), Stable (1.0x), Weakening (0.7x), Exhaustion (0.5x).*

#### B. Impact Mapping & Cluster Rule
- **Weights**: USD/Oil ($\uparrow \to -1$), UST10Y Price ($\uparrow \to +1$), Gold ($\pm 0.5$).
- **Cluster Rule**: Để tránh tính toán lặp (Double counting), nếu USD, Rates và Oil cùng chiều, hệ thống chỉ lấy giá trị có biên độ lớn nhất (**Max Magnitude**) làm đại diện cho cụm áp lực vĩ mô.
- **Normalization Formula**:
    \[
    S_t = \text{Clamp}\left( \frac{\sum Impact_{adj}}{6} \times 10, -10, 10 \right)
    \]
    *Hệ thống áp dụng Stability Filter triệt tiêu các giá trị trong vùng [-0.5, 0.5] về 0 để loại bỏ nhiễu.*

- **State Transitions**: Nghiên cứu tập trung vào sự thay đổi trạng thái ($S_{t-1} \to S_t$) như một tiền đề tiềm năng cho biến động giá.

### 2.2 Data Architecture & Limitations
- **Source**: Dữ liệu H1 từ MT5, tự động đồng bộ.
- **Pipeline**: The data processing pipeline ensures consistent feature computation and reproducibility across all observations.
- **Sample Size**: 199 bản ghi hợp nhất. Kích thước mẫu này chưa đủ lớn để thực hiện các suy diễn kinh tế lượng (econometric inference) phức tạp.
- **Statistical Significance**: Các kết quả hiện tại có p-value cao, do đó không thể coi là các kết luận xác thực (confirmed effects) mà chỉ là các quan sát thực nghiệm sơ khởi.

---

## 3. Core Observations
### 3.1 Flow as a Proxy for Market Activity
Flow divergence is associated with higher-than-baseline returns, suggesting that the signal captures periods of elevated market activity or instability rather than providing a consistent directional bias. Baseline returns correspond to the unconditional mean returns of USTEC over the sample. Điều này gợi ý rằng Flow có thể đang ghi lại các giai đoạn tích lũy áp lực vĩ mô đáng kể.

### 3.2 Key Transition Patterns (Observational)
Dựa trên Ma trận Chuyển đổi (Appendix), một số mẫu hình lặp lại đáng chú ý (dù N còn nhỏ):
- **Tail Opportunities**: Các bước nhảy từ vùng âm cực đoan (-6 → -2) đi kèm với lợi nhuận dương lớn, gợi ý về khả năng nhận diện các pha cạn kiệt lực bán.
- **Regime Shifts**: Các bước chuyển qua lại mức 0 thường mang lại thông tin về sự thay đổi trạng thái tâm lý thị trường rõ rệt hơn là các mức Flow cố định.

---

## 4. Preliminary Analysis: The Lag Hypothesis
Preliminary evidence suggests an asymmetric response between flow transitions and price reactions:
- **Delayed Bearish Response**: Các tín hiệu suy yếu (như +1 → 0) thường không làm giá giảm ngay lập tức ở H+1 nhưng cho thấy sự sụt giảm đáng kể ở H+2 (-0.89%).
- **Immediate Bullish Response**: Ngược lại, các pha cải thiện Flow từ vùng thấp có xu hướng được phản ánh vào giá nhanh hơn (ngay trong H+1).

---

## 5. Potential Applications (Exploratory)
The framework is better interpreted as a state-filtering mechanism within a broader decision system, rather than a standalone predictive model. Các hướng ứng dụng tiềm năng:
- **Regime Detection**: Nhận diện các giai đoạn thị trường ổn định vs. bất ổn.
- **Risk Filtering**: Sử dụng các pha sụt giảm Flow mạnh làm bộ lọc rủi ro, cảnh báo khả năng đảo chiều tiềm ẩn dù giá vẫn đang trong đà tăng.
- **Hypothesis Refinement**: Làm cơ sở để xây dựng các mô hình kiểm chứng phức tạp hơn với dữ liệu độ phân giải cao (Intraday).

---

## 6. Risk Assessment & Limitations
- **Cherry Picking Risk**: Các kịch bản Transition có N nhỏ (N=1, 2) mang tính chất minh họa kịch bản cực đoan, không đại diện cho quy luật chung.
- **Subjectivity**: Mặc dù thuật toán là xác định, các tham số đầu vào (Direction, Speed) vẫn mang tính chất heuristic.
- **Statistical Power**: Cần mở rộng dữ liệu lên N > 500 và áp dụng các kiểm định Robustness. 
- **Future Work**: Future work will focus on formal statistical validation, including out-of-sample testing, bootstrap methods, and regime stability analysis.

---

## Appendix: Full Transition Matrix Analysis (199 obs)
*Note: Most transitions have small sample sizes (N ≤ 3) and should be interpreted as illustrative rather than statistically reliable.*

| Transition (S_prev → S_curr) | N | Mean R(H+1) | Mean R(H+2) |
|-----------------------------|---|-------------|-------------|
| **Source: S = -6**          |   |             |             |
| (-6 → -7)                   | 1 | +2.6892%    | +3.7963%    |
| (-6 → -2)                   | 1 | +3.9428%    | +5.5415%    |
| (-6 → +0)                   | 1 | +0.6329%    | +0.2962%    |
| (-6 → +2)                   | 2 | -0.0978%    | -0.8968%    |
| (-6 → +3)                   | 1 | +1.5203%    | +1.7365%    |
| **Source: S = -5**          |   |             |             |
| (-5 → -3)                   | 1 | +0.6507%    | +1.2042%    |
| (-5 → +0)                   | 1 | +1.9246%    | +2.5799%    |
| (-5 → +2)                   | 1 | -0.6766%    | -1.5433%    |
| (-5 → +3)                   | 1 | +0.7483%    | +0.6336%    |
| **Source: S = -4**          |   |             |             |
| (-4 → +0)                   | 1 | +0.9447%    | +1.9031%    |
| (-4 → +4)                   | 1 | +0.9785%    | +0.9982%    |
| **Source: S = -3**          |   |             |             |
| (-3 → -6)                   | 1 | +0.1438%    | +0.7776%    |
| (-3 → -4)                   | 1 | +0.7560%    | +1.7419%    |
| (-3 → -2)                   | 3 | -0.4088%    | +0.2473%    |
| (-3 → -1)                   | 4 | -0.3485%    | -1.1308%    |
| (-3 → +0)                   | 3 | +0.4045%    | +0.1786%    |
| (-3 → +1)                   | 4 | -0.0889%    | -0.6320%    |
| (-3 → +3)                   | 1 | +0.9255%    | +0.9930%    |
| (-3 → +6)                   | 1 | +2.9521%    | +2.3058%    |
| **Source: S = -2**          |   |             |             |
| (-2 → -3)                   | 2 | -0.3636%    | -0.1643%    |
| (-2 → -1)                   | 1 | +0.2958%    | +0.1300%    |
| (-2 → +0)                   | 3 | -0.4064%    | -1.6568%    |
| (-2 → +1)                   | 5 | +0.3857%    | +0.6258%    |
| (-2 → +3)                   | 4 | +0.3674%    | +1.4247%    |
| (-2 → +4)                   | 1 | -0.3758%    | +1.6039%    |
| (-2 → +5)                   | 1 | +0.2141%    | +0.8995%    |
| (-2 → +6)                   | 1 | +1.7848%    | +1.0735%    |
| (-2 → +9)                   | 1 | +0.1277%    | -0.5557%    |
| (-2 → +10)                  | 1 | -0.3003%    | +0.0913%    |
| **Source: S = -1**          |   |             |             |
| (-1 → -6)                   | 3 | +0.9477%    | +3.1207%    |
| (-1 → -5)                   | 1 | -0.7627%    | -0.7113%    |
| (-1 → -3)                   | 1 | -0.1681%    | +0.5867%    |
| (-1 → -2)                   | 3 | -0.3065%    | +0.5803%    |
| (-1 → +0)                   | 5 | -0.5355%    | -0.0182%    |
| (-1 → +1)                   | 2 | +1.0099%    | +0.9656%    |
| (-1 → +2)                   | 3 | -0.6842%    | -1.1958%    |
| (-1 → +3)                   | 2 | +0.7398%    | -0.1291%    |
| (-1 → +5)                   | 1 | +0.0352%    | -0.0310%    |
| **Source: S = +0**          |   |             |             |
| (+0 → -5)                   | 2 | +0.5171%    | +1.8630%    |
| (+0 → -3)                   | 2 | -2.7265%    | -1.1142%    |
| (+0 → -2)                   | 3 | -0.0711%    | -0.6847%    |
| (+0 → -1)                   | 4 | -0.0173%    | -0.0801%    |
| (+0 → +1)                   | 5 | -0.3729%    | -0.3983%    |
| (+0 → +2)                   | 8 | +0.2786%    | +0.7655%    |
| (+0 → +3)                   | 3 | +0.5341%    | +1.2444%    |
| (+0 → +5)                   | 1 | +0.8186%    | +0.1771%    |
| (+0 → +6)                   | 1 | +0.9600%    | +2.1219%    |
| **Source: S = +1**          |   |             |             |
| (+1 → -5)                   | 1 | +1.5963%    | +0.9088%    |
| (+1 → -4)                   | 1 | -0.9107%    | +0.0253%    |
| (+1 → -3)                   | 4 | -0.1039%    | -1.0082%    |
| (+1 → -2)                   | 4 | +0.7056%    | +0.7303%    |
| (+1 → -1)                   | 4 | -0.2742%    | +0.7332%    |
| (+1 → +0)                   | 8 | +0.0074%    | -0.8957%    |
| (+1 → +2)                   | 1 | -2.6973%    | -3.1178%    |
| (+1 → +4)                   | 1 | +0.6171%    | -0.4693%    |
| (+1 → +5)                   | 1 | +0.4155%    | +1.3352%    |
| **Source: S = +2**          |   |             |             |
| (+2 → -6)                   | 1 | -0.5233%    | -0.5492%    |
| (+2 → -5)                   | 1 | +0.9820%    | +1.6391%    |
| (+2 → -3)                   | 4 | +0.3185%    | +0.6338%    |
| (+2 → -2)                   | 2 | -1.3651%    | -0.8011%    |
| (+2 → -1)                   | 3 | +0.4719%    | +0.7471%    |
| (+2 → +0)                   | 2 | +0.6933%    | +0.6562%    |
| (+2 → +1)                   | 1 | -0.8726%    | -0.4607%    |
| (+2 → +3)                   | 1 | -1.2874%    | +0.0860%    |
| **Source: S = +3**          |   |             |             |
| (+3 → -3)                   | 2 | +0.7434%    | +0.0817%    |
| (+3 → -2)                   | 1 | +0.4835%    | +0.6986%    |
| (+3 → -1)                   | 3 | +1.3586%    | +1.5609%    |
| (+3 → +0)                   | 1 | +0.7225%    | +1.5079%    |
| (+3 → +1)                   | 5 | -0.2091%    | +0.0138%    |
| (+3 → +5)                   | 1 | +0.4838%    | +0.7941%    |
| **Source: S = +4**          |   |             |             |
| (+4 → -2)                   | 1 | +0.0195%    | -0.4795%    |
| (+4 → -1)                   | 1 | -1.0798%    | -2.3919%    |
| (+4 → +1)                   | 1 | +1.9872%    | +1.7565%    |
| **Source: S = +5**          |   |             |             |
| (+5 → -1)                   | 2 | +0.4398%    | +0.6973%    |
| (+5 → +0)                   | 2 | -0.1637%    | +0.3210%    |
| (+5 → +2)                   | 1 | -0.0661%    | -0.5891%    |
| (+5 → +3)                   | 1 | +0.6839%    | +1.6661%    |
| **Source: S = +6**          |   |             |             |
| (+6 → -8)                   | 1 | +1.1509%    | +0.9408%    |
| (+6 → +0)                   | 1 | -0.6277%    | +0.1858%    |
| (+6 → +1)                   | 1 | -0.6989%    | +0.5364%    |